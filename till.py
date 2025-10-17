import streamlit as st
import pandas as pd
import uuid
from datetime import datetime
import csv
import os


# Get the directory where this script is located
script_dir = os.path.dirname(os.path.abspath(__file__))

# Build file paths relative to the script's directory
INVENTORY_FILE = os.path.join(script_dir,"inventory.xlsx")
SALES_FILE = os.path.join(script_dir, "sales_log.csv")

# --- Load inventory
try:
    inventory_df = pd.read_excel(INVENTORY_FILE, dtype={"barcode": str})
except FileNotFoundError:
    st.error(f"Inventory file not found at: {INVENTORY_FILE}")
    st.stop()

inventory_df.columns = inventory_df.columns.str.strip()

# Ensure reorder_level column exists, else add default 10
if "reorder_level" not in inventory_df.columns:
    inventory_df["reorder_level"] = 10

inventory_df = inventory_df[inventory_df["is_active"] == True]

# Make PRODUCTS dict from inventory_df
PRODUCTS = inventory_df.set_index("barcode").to_dict(orient="index")

# --- Session state
if "cart" not in st.session_state:
    st.session_state.cart = []
if "member_id" not in st.session_state:
    st.session_state.member_id = ""
if "barcode_input" not in st.session_state:
    st.session_state.barcode_input = ""
if "qty_input" not in st.session_state:
    st.session_state.qty_input = 1
if "discount" not in st.session_state:
    st.session_state.discount = 0
if "discount_type" not in st.session_state:
    st.session_state.discount_type = "percent"

# --- Ensure sales log exists
if not os.path.exists(SALES_FILE):
    with open(SALES_FILE, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "sale_id", "timestamp", "membership_id", "barcode", "product_name",
            "category", "qty", "unit_price", "line_total", "discount"
        ])

# --- Helper functions
def add_to_cart(barcode, qty=1):
    product = PRODUCTS.get(barcode)
    if not product:
        st.warning(f"Barcode {barcode} not found in inventory")
        return
    
    # Check stock availability
    current_stock = product.get("stock_qty", 0)
    if qty > current_stock:
        st.warning(f"Not enough stock for {product['name']}. Available: {current_stock}")
        return

    for line in st.session_state.cart:
        if line["barcode"] == barcode:
            if line["qty"] + qty > current_stock:
                st.warning(f"Cannot add {qty} more {product['name']}. Only {current_stock - line['qty']} left in stock.")
                return
            line["qty"] += qty
            return
    line = {
        "id": str(uuid.uuid4()),
        "barcode": barcode,
        "name": product["name"],
        "qty": qty,
        "unit_price": product["price"],
        "category": product["category"],
        "pack_size": product.get("pack_size", ""),
    }
    st.session_state.cart.append(line)

def remove_one_from_cart(line_id):
    for line in st.session_state.cart:
        if line["id"] == line_id:
            if line["qty"] > 1:
                line["qty"] -= 1
            else:
                st.session_state.cart = [l for l in st.session_state.cart if l["id"] != line_id]
            break

def calc_totals():
    subtotal = sum(line["unit_price"] * line["qty"] for line in st.session_state.cart)
    
    if st.session_state.discount_type == "percent":
        discount_amount = (st.session_state.discount / 100) * subtotal
    else:
        discount_amount = st.session_state.discount

    total = subtotal - discount_amount
    return subtotal, discount_amount, total

def save_sale(cart, member_id):
    sale_id = str(uuid.uuid4())
    ts = datetime.now().isoformat(timespec="seconds")
    discount_applied = st.session_state.discount

    with open(SALES_FILE, "a", newline="") as f:
        writer = csv.writer(f)
        for line in cart:
            line_total = line["unit_price"] * line["qty"]
            if st.session_state.discount_type == "percent" and discount_applied > 0:
                line_total -= (line_total * discount_applied / 100)
            elif st.session_state.discount_type == "fixed":
                cart_total = sum(l["unit_price"] * l["qty"] for l in cart)
                if cart_total > 0:
                    discount_share = (line_total / cart_total) * discount_applied
                    line_total -= discount_share
            writer.writerow([
                sale_id, ts, member_id, line["barcode"], line["name"],
                line["category"], line["qty"], line["unit_price"],
                round(line_total, 2), discount_applied
            ])

def update_inventory_after_checkout(cart):
    global inventory_df, PRODUCTS
    for line in cart:
        barcode = line["barcode"]
        qty_sold = line["qty"]
        # Find the row index for this barcode
        idx = inventory_df.index[inventory_df["barcode"] == barcode].tolist()
        if not idx:
            continue  # Not found, skip
        idx = idx[0]
        current_stock = inventory_df.at[idx, "stock_qty"]
        new_stock = max(current_stock - qty_sold, 0)
        inventory_df.at[idx, "stock_qty"] = new_stock
        # Update PRODUCTS dict as well for consistency
        PRODUCTS[barcode]["stock_qty"] = new_stock

    # Save inventory back to Excel file
    try:
        inventory_df.to_excel(INVENTORY_FILE, index=False)
    except Exception as e:
        st.error(f"Failed to save updated inventory: {e}")

def checkout():
    cart_copy = st.session_state.cart.copy()
    member_id = st.session_state.member_id

    # Check stock again before checkout (just in case)
    for line in cart_copy:
        product = PRODUCTS.get(line["barcode"])
        if product is None:
            st.error(f"Product {line['name']} not found in inventory at checkout.")
            return
        if line["qty"] > product.get("stock_qty", 0):
            st.error(f"Insufficient stock for {line['name']} at checkout. Please adjust quantity.")
            return

    save_sale(cart_copy, member_id)
    update_inventory_after_checkout(cart_copy)

    st.session_state.cart = []
    st.session_state.member_id = ""
    st.session_state.discount = 0
    st.success(f"✅ Sale saved at {datetime.now().strftime('%H:%M:%S')} (Member: {member_id or 'N/A'})")

def handle_scan():
    code = str(st.session_state.barcode_input).strip()
    try:
        qty = int(st.session_state.qty_input)
        if qty <= 0:
            st.warning("Quantity must be greater than 0")
            return
    except:
        st.warning("Invalid quantity")
        return

    if code:
        add_to_cart(code, qty)

    st.session_state.barcode_input = ""
    st.session_state.qty_input = 1

# --- UI
st.title("🛒 Simple Till System")

# Membership input
st.session_state.member_id = st.text_input("Membership ID (optional)", value=st.session_state.member_id)

# Barcode & quantity input
col1, col2 = st.columns([2, 1])
with col1:
    st.text_input("Scan or type barcode", key="barcode_input", on_change=handle_scan)
with col2:
    st.number_input("Qty", min_value=1, step=1, key="qty_input")

# Product search
product_names = {v['name']: k for k, v in PRODUCTS.items()}
selected_name = st.selectbox("Search product by name", [""] + list(product_names.keys()))
if selected_name:
    add_to_cart(product_names[selected_name])

# Discount
discount_type = st.radio("Discount Type", options=["Percentage", "Fixed Amount"], index=0)
if discount_type == "Percentage":
    discount_value = st.number_input("Discount (%)", min_value=0, step=1, key="discount_percent")
    st.session_state.discount = discount_value
    st.session_state.discount_type = "percent"
else:
    discount_value = st.number_input("Discount (R)", min_value=0.0, step=1.0, key="discount_fixed")
    st.session_state.discount = discount_value
    st.session_state.discount_type = "fixed"

# Cart Display
st.subheader("🛒 Cart")
if st.session_state.cart:
    low_stock_items = []
    for line in st.session_state.cart:
        st.write(f"{line['qty']} × {line['name']} ({line.get('pack_size','')}) @ R{line['unit_price']:.2f}")

        # Reorder warning if stock after sale <= reorder_level
        product = PRODUCTS.get(line["barcode"])
        if product:
            remaining_stock = product.get("stock_qty", 0) - line["qty"]
            reorder_level = product.get("reorder_level", 10)
            if remaining_stock <= reorder_level:
                low_stock_items.append(f"{line['name']} (Remaining: {remaining_stock})")

        st.button(f"Remove 1 ({line['name']})", key=f"remove_{line['id']}", on_click=remove_one_from_cart, args=(line['id'],))

    if low_stock_items:
        st.warning("⚠️ Reorder warning for: " + ", ".join(low_stock_items))

    subtotal, discount_amount, total = calc_totals()
    st.markdown(f"**Subtotal: R{subtotal:.2f}**")
    if discount_amount:
        st.markdown(f"**Discount: -R{discount_amount:.2f}**")
    st.markdown(f"### Total: R{total:.2f}")

    st.button("✅ Checkout", on_click=checkout)
else:
    st.info("Cart is empty.")

# Optional Views
if st.checkbox("📦 Show Inventory"):
    st.dataframe(inventory_df)

if st.checkbox("📄 Show Recent Sales"):
    try:
        sales_log_df = pd.read_csv(SALES_FILE)
        st.dataframe(sales_log_df.tail(20))
        st.download_button("Download Sales Log", data=sales_log_df.to_csv(index=False), file_name="sales_log.csv")
    except Exception as e:
        st.error(f"Error reading sales log: {e}")
