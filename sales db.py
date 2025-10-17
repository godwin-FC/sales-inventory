import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import os
from streamlit_autorefresh import st_autorefresh

# Auto-refresh every 60 seconds (10,000 ms)
st_autorefresh(interval=30 * 1000, limit=None, key="datarefresh")
st.set_page_config(page_title="Sales & Inventory Dashboard", layout="wide")



# Get the directory where this script is located
script_dir = os.path.dirname(os.path.abspath(__file__))

# Build file paths relative to the script's directory
INVENTORY_FILE = os.path.join(script_dir, "inventory.xlsx")
SALES_FILE = os.path.join(script_dir, "sales_log.csv")




@st.cache_data(ttl=10)
def load_inventory():
    df = pd.read_excel(INVENTORY_FILE, dtype={"barcode": str})
    df.columns = df.columns.str.strip()
    return df

@st.cache_data(ttl=10)
def load_sales():
    df = pd.read_csv(SALES_FILE, dtype={"barcode": str})
    df.columns = df.columns.str.strip()
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df['discount'] = df.get('discount', 0).fillna(0)
    return df

inventory_df = load_inventory()
sales_df = load_sales()

# Merge sales with inventory
sales_merged = sales_df.merge(
    inventory_df[['barcode', 'category', 'brand', 'supplier', 'cost_price', 'name', 'stock_qty', 'reorder_level']],
    on='barcode',
    how='left',
    suffixes=('', '_inv')
)

# Sidebar filters
st.sidebar.header("Filters")
max_date = sales_merged['timestamp'].max().date()
min_date = max_date - timedelta(days=90)
date_range = st.sidebar.date_input("Date range", [min_date, max_date], min_value=min_date, max_value=max_date)

all_categories = sorted(sales_merged['category'].dropna().unique())
selected_categories = st.sidebar.multiselect("Category", options=all_categories, default=all_categories)

all_brands = sorted(sales_merged['brand'].dropna().unique())
selected_brands = st.sidebar.multiselect("Brand", options=all_brands, default=all_brands)

sales_filtered = sales_merged[
    (sales_merged['timestamp'].dt.date >= date_range[0]) &
    (sales_merged['timestamp'].dt.date <= date_range[1]) &
    (sales_merged['category'].isin(selected_categories)) &
    (sales_merged['brand'].isin(selected_brands))
]

# KPI calculations
total_sales = sales_filtered['line_total'].sum()
total_units = sales_filtered['qty'].sum()
avg_discount = sales_filtered['discount'].mean()

sales_filtered['cost'] = sales_filtered['cost_price'] * sales_filtered['qty']
total_cost = sales_filtered['cost'].sum()
total_profit = total_sales - total_cost

# Average units per day
days_in_range = (date_range[1] - date_range[0]).days + 1
avg_units_per_day_global = total_units / days_in_range if days_in_range > 0 else 0

# Per product stats
product_stats = sales_filtered.groupby('product_name').agg(
    total_units=('qty', 'sum'),
    total_sales=('line_total', 'sum'),
    days_sold=('timestamp', lambda x: x.dt.date.nunique())
).reset_index()

product_stats['avg_units_per_day'] = product_stats['total_units'] / days_in_range
product_stats['sales_frequency_pct'] = product_stats['days_sold'] / days_in_range * 100
product_stats['avg_sales_per_day'] = product_stats['total_sales'] / days_in_range

product_stats = product_stats.sort_values('total_units', ascending=False)

# Reorder / low stock logic
sales_filtered['month'] = sales_filtered['timestamp'].dt.to_period('M')
monthly_sales_per_product = sales_filtered.groupby(['barcode', 'month'])['qty'].sum().groupby('barcode').mean()

reorder_levels = monthly_sales_per_product.apply(lambda x: max(int(np.ceil(x * 2)), 5))
reorder_levels = reorder_levels.rename('dynamic_reorder_level').reset_index()

inventory_with_reorder = inventory_df.merge(reorder_levels, on='barcode', how='left')
inventory_with_reorder['reorder_level'] = inventory_with_reorder['reorder_level'].fillna(
    inventory_with_reorder['dynamic_reorder_level']
).fillna(5)

low_stock_df = inventory_with_reorder[inventory_with_reorder['stock_qty'] <= inventory_with_reorder['reorder_level']]

# Sales by category / brand
def calc_profit(df):
    return (df['line_total'] - df['cost_price'] * df['qty']).sum()

sales_by_category = sales_filtered.groupby('category').agg(
    total_sales=('line_total', 'sum'),
    units_sold=('qty', 'sum'),
    avg_discount=('discount', 'mean'),
    profit=('qty', lambda x: calc_profit(sales_filtered.loc[x.index]))
).sort_values('total_sales', ascending=False)

sales_by_brand = sales_filtered.groupby('brand').agg(
    total_sales=('line_total', 'sum'),
    units_sold=('qty', 'sum'),
    avg_discount=('discount', 'mean'),
    profit=('qty', lambda x: calc_profit(sales_filtered.loc[x.index]))
).sort_values('total_sales', ascending=False)

# Membership / discount impact
membership_sales = sales_filtered.groupby('membership_id').agg(
    total_sales=('line_total', 'sum'),
    units_sold=('qty', 'sum'),
    avg_discount=('discount', 'mean'),
    count_sales=('sale_id', 'nunique')
).sort_values('total_sales', ascending=False)

discount_impact = sales_filtered.groupby('category').agg(
    avg_discount=('discount', 'mean'),
    total_sales=('line_total', 'sum')
).sort_values('avg_discount', ascending=False)

monthly_sales = sales_filtered.groupby(sales_filtered['timestamp'].dt.to_period('M')).agg(
    total_sales=('line_total', 'sum'),
    units_sold=('qty', 'sum')
).reset_index()
monthly_sales['timestamp'] = monthly_sales['timestamp'].dt.to_timestamp()

# Tab logic with session_state to preserve tab across refresh
tabs = [
    "Summary KPIs", "Sales Analysis", "Top Products",
    "Inventory Status", "Membership Analysis", "Discount Impact", "Raw Data"
]

if "active_tab" not in st.session_state:
    st.session_state.active_tab = tabs[0]

# Display buttons as tiles
st.markdown("### Navigate")
cols = st.columns(len(tabs))

for i, tab_name in enumerate(tabs):
    if cols[i].button(tab_name):
        st.session_state.active_tab = tab_name

# Set current tab
sel = st.session_state.active_tab

st.title("📊 Sales & Inventory Dashboard")

if sel == "Summary KPIs":
    st.header("Summary KPIs")

    # First row of KPIs
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total Sales (R)", f"R {total_sales:,.2f}")
    c2.metric("Units Sold", f"{total_units:,}")
    c3.metric("Avg Discount (%)", f"{avg_discount:.2f}")
    c4.metric("Total Profit (R)", f"R {total_profit:,.2f}")
    c5.metric("Total Cost (R)", f"R {total_cost:,.2f}")

    # Second row of KPIs
    c6, c7, c8, c9, c10 = st.columns(5)
    c6.metric("Avg Units/Day", f"{avg_units_per_day_global:.2f}")
    c7.metric("Low Stock Count", f"{len(low_stock_df)}")
    c8.metric("Active Products", f"{inventory_df[inventory_df['is_active'] == True]['barcode'].nunique()}")
    c9.metric("Unique Customers", f"{sales_filtered['membership_id'].nunique()}")
    c10.metric("Avg Sale Value (R)", f"R {total_sales / max(1, sales_filtered['sale_id'].nunique()):,.2f}")


elif sel == "Sales Analysis":
    st.header("Sales by Category & Brand")
    st.subheader("By Category")
    st.bar_chart(sales_by_category['total_sales'])
    st.subheader("By Brand")
    st.bar_chart(sales_by_brand['total_sales'])
    st.subheader("Monthly Sales Trend")
    st.line_chart(monthly_sales.set_index('timestamp')['total_sales'])

elif sel == "Top Products":
    st.header("Top Products with Averages")
    num_top = st.slider("Show top N products", min_value=5, max_value=50, value=10)
    top_subset = product_stats.head(num_top)

    st.metric("Avg Units/Day (global)", f"{avg_units_per_day_global:.2f}")

    st.subheader("Avg Units per Day – Top Products")
    st.bar_chart(top_subset.set_index('product_name')['avg_units_per_day'])

    st.subheader("Units Sold vs Sales Frequency")
    fig, ax = plt.subplots(figsize=(10, 5))
    ax2 = ax.twinx()
    ax.bar(top_subset['product_name'], top_subset['total_units'], color='skyblue', label='Units Sold')
    ax.set_ylabel("Units Sold", color='skyblue')
    ax2.plot(top_subset['product_name'], top_subset['sales_frequency_pct'], color='orange', marker='o', label='Freq %')
    ax2.set_ylabel("Sales Frequency (%)", color='orange')
    plt.xticks(rotation=45, ha='right')
    st.pyplot(fig)

    st.subheader("Detailed Stats")
    st.dataframe(
        top_subset.style.format({
            'avg_units_per_day': '{:.2f}',
            'sales_frequency_pct': '{:.1f} %',
            'total_sales': 'R{:.2f}',
            'total_units': '{:,}'
        })
    )

elif sel == "Inventory Status":
    st.header("Inventory / Reorder Status")

    if not low_stock_df.empty:
        low_stock_df = low_stock_df.copy()

        # Get average monthly sales per barcode from earlier calculation
        avg_monthly_sales = monthly_sales_per_product.reindex(low_stock_df['barcode']).fillna(0)

        # Calculate reorder qty based on 2 months average sales minus current stock
        low_stock_df['avg_monthly_sales'] = avg_monthly_sales.values
        low_stock_df['reorder_qty'] = (2 * low_stock_df['avg_monthly_sales'] - low_stock_df['stock_qty']).apply(lambda x: max(x, 0)).astype(int)

        st.subheader("Low-stock Items (with reorder quantities)")
        st.dataframe(
            low_stock_df[['barcode', 'name', 'category', 'stock_qty', 'reorder_level', 'avg_monthly_sales', 'reorder_qty', 'supplier']]
        )
    else:
        st.info("No low-stock items.")

    st.subheader("Full Inventory")
    st.dataframe(inventory_with_reorder)


elif sel == "Membership Analysis":
    st.header("Membership Sales")
    st.bar_chart(membership_sales['total_sales'].head(10))
    st.dataframe(membership_sales.style.format({
        'total_sales': 'R{:.2f}', 
        'units_sold': '{:,}', 
        'avg_discount': '{:.2f}'
    }))

elif sel == "Discount Impact":
    st.header("Discount Impact by Category")
    st.bar_chart(discount_impact['avg_discount'])
    st.dataframe(discount_impact.style.format({
        'avg_discount': '{:.2f}', 
        'total_sales': 'R{:.2f}'
    }))

elif sel == "Raw Data":
    st.header("Raw Data Views")
    st.subheader("Sales (filtered)")
    st.dataframe(sales_filtered)
    st.download_button("Download Sales CSV", data=sales_filtered.to_csv(index=False), file_name="sales_filtered.csv")
    st.subheader("Inventory with Reorder Info")
    st.dataframe(inventory_with_reorder)
    st.download_button("Download Inventory CSV", data=inventory_with_reorder.to_csv(index=False), file_name="inventory.csv")
