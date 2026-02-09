import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
import gspread
from google.oauth2.service_account import Credentials

# --- KONFIGURASI HALAMAN PROFESIONAL ---
st.set_page_config(
    page_title="Supply Chain Command Center | Flagship Store",
    page_icon="🏭",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- CUSTOM CSS UNTUK TAMPILAN PREMIUM ---
st.markdown("""
<style>
    .main-header {
        font-size: 2.8rem !important;
        color: #1E3A8A !important;
        font-weight: 700;
        padding-bottom: 0.5rem;
        border-bottom: 3px solid #3B82F6;
        margin-bottom: 1.5rem;
    }
    .metric-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 1.5rem;
        border-radius: 15px;
        color: white;
        box-shadow: 0 10px 20px rgba(0,0,0,0.1);
    }
    .metric-title {
        font-size: 0.9rem;
        opacity: 0.9;
        text-transform: uppercase;
        letter-spacing: 1px;
        margin-bottom: 0.5rem;
    }
    .metric-value {
        font-size: 2.2rem !important;
        font-weight: 700;
        margin-bottom: 0.2rem;
    }
    .metric-change {
        font-size: 0.9rem;
        opacity: 0.9;
    }
    .status-badge {
        padding: 0.25rem 0.75rem;
        border-radius: 20px;
        font-size: 0.8rem;
        font-weight: 600;
        display: inline-block;
    }
    .stProgress > div > div > div > div {
        background-color: #3B82F6;
    }
    .store-card {
        background: white;
        padding: 1.5rem;
        border-radius: 12px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.08);
        border-left: 4px solid #3B82F6;
        margin-bottom: 1rem;
    }
    .tab-container {
        background: white;
        padding: 1.5rem;
        border-radius: 12px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.05);
        margin-top: 1rem;
    }
</style>
""", unsafe_allow_html=True)

# --- KONEKSI KE GOOGLE SHEETS (DI CACHE) ---
@st.cache_data(ttl=300, show_spinner="🔄 Loading real-time data from Google Sheets...")
def load_data():
    scope = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    credentials = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"], scopes=scope
    )
    gc = gspread.authorize(credentials)
    
    # Load Kamus Store
    try:
        sh_kamus = gc.open("Offline Store Kamus")
        ws_kamus = sh_kamus.get_worksheet(0)
        df_kamus = pd.DataFrame(ws_kamus.get_all_records())
    except:
        st.error("⚠️ File 'Offline Store Kamus' tidak ditemukan!")
        df_kamus = pd.DataFrame()
    
    # List semua spreadsheet
    all_files = gc.list_spreadsheet_files()
    
    # Cari file berdasarkan pattern
    file_ids = {
        'export': None,
        'amb': None,
        'bsb': None,
        'mcd': None
    }
    
    for f in all_files:
        name = f['name'].lower()
        if 'export_' in name and 'xlsx' not in name:
            file_ids['export'] = f['id']
        elif 'source_amb' in name:
            file_ids['amb'] = f['id']
        elif 'source_bsb' in name:
            file_ids['bsb'] = f['id']
        elif 'source_mcd' in name:
            file_ids['mcd'] = f['id']
    
    # Load Sales Data
    if file_ids['export']:
        ws_sales = gc.open_by_key(file_ids['export']).get_worksheet(0)
        df_sales = pd.DataFrame(ws_sales.get_all_records())
        cols_sales = ['Ordernumber', 'Orderdate', 'ItemSKU', 'ItemPrice', 'ItemOrdered']
        df_sales = df_sales[cols_sales] if all(col in df_sales.columns for col in cols_sales) else df_sales
    else:
        st.error("❌ File sales (export_) tidak ditemukan!")
        df_sales = pd.DataFrame()
    
    # Load Stock Data
    stock_dfs = []
    store_mapping = {'amb': 'AMB', 'bsb': 'BSB', 'mcd': 'MCD'}
    
    for key, store_name in store_mapping.items():
        if file_ids[key]:
            try:
                ws = gc.open_by_key(file_ids[key]).get_worksheet(0)
                df = pd.DataFrame(ws.get_all_records())
                if len(df) > 0:
                    # Standardize column names
                    col_mapping = {}
                    for col in df.columns:
                        col_lower = col.lower()
                        if 'location' in col_lower or 'store' in col_lower:
                            col_mapping[col] = 'Location Code'
                        elif 'sku' in col_lower:
                            col_mapping[col] = 'SKU'
                        elif 'total' in col_lower or 'stock' in col_lower or 'qty' in col_lower:
                            col_mapping[col] = 'Total'
                    
                    df = df.rename(columns=col_mapping)
                    required_cols = ['Location Code', 'SKU', 'Total']
                    
                    if all(col in df.columns for col in required_cols):
                        df['Store_Name'] = store_name
                        stock_dfs.append(df[['Location Code', 'SKU', 'Total', 'Store_Name']])
            except Exception as e:
                st.warning(f"⚠️ Gagal load stock data untuk {store_name}: {e}")
    
    df_stock_total = pd.concat(stock_dfs, ignore_index=True) if stock_dfs else pd.DataFrame()
    
    return df_sales, df_kamus, df_stock_total

# --- FUNGSI HELPER UNTUK ANALISIS ---
def calculate_stock_health(df_stock, df_sales_mapped, store_name=None):
    """Hitung health metrics untuk stock"""
    
    if store_name:
        stock_data = df_stock[df_stock['Store_Name'] == store_name].copy()
        sales_data = df_sales_mapped[df_sales_mapped['Store_Name'] == store_name].copy()
    else:
        stock_data = df_stock.copy()
        sales_data = df_sales_mapped.copy()
    
    if stock_data.empty:
        return pd.DataFrame()
    
    # Hitung sales 3 bulan terakhir per SKU
    current_date = datetime.now()
    start_date_3mo = current_date - timedelta(days=90)
    
    sales_data['Orderdate'] = pd.to_datetime(sales_data['Orderdate'], errors='coerce')
    recent_sales = sales_data[sales_data['Orderdate'] >= start_date_3mo]
    
    sku_sales = recent_sales.groupby('ItemSKU').agg({
        'ItemOrdered': 'sum',
        'ItemPrice': 'mean'
    }).reset_index()
    sku_sales.columns = ['SKU', 'Qty_3Mo', 'Avg_Price']
    sku_sales['AMS'] = sku_sales['Qty_3Mo'] / 3
    
    # Gabungkan dengan stock
    analysis_df = stock_data.groupby(['SKU', 'Store_Name']).agg({'Total': 'sum'}).reset_index()
    analysis_df = pd.merge(analysis_df, sku_sales, on='SKU', how='left')
    
    # Fill NaN values
    analysis_df['Qty_3Mo'] = analysis_df['Qty_3Mo'].fillna(0)
    analysis_df['AMS'] = analysis_df['AMS'].fillna(0)
    analysis_df['Avg_Price'] = analysis_df['Avg_Price'].fillna(analysis_df['Avg_Price'].median() if not analysis_df['Avg_Price'].isna().all() else 0)
    
    # Hitung Month Cover
    analysis_df['Month_Cover'] = np.where(
        analysis_df['AMS'] > 0,
        analysis_df['Total'] / analysis_df['AMS'],
        999  # Jika tidak ada sales
    )
    
    # Hitung nilai stock
    analysis_df['Stock_Value'] = analysis_df['Total'] * analysis_df['Avg_Price']
    
    # Klasifikasi Status
    def classify_status(row):
        if row['Total'] > 0 and row['AMS'] == 0:
            return "📦 New/Dead Stock"
        elif row['Month_Cover'] < 0.5:
            return "🚨 Critical"
        elif row['Month_Cover'] < 1:
            return "⚠️ Need Reorder"
        elif row['Month_Cover'] <= 1.5:
            return "✅ Healthy"
        elif row['Month_Cover'] <= 3:
            return "📈 Good Buffer"
        else:
            return "🛑 Overstock"
    
    analysis_df['Status'] = analysis_df.apply(classify_status, axis=1)
    
    # Urutan status untuk sorting
    status_order = {
        "🚨 Critical": 1,
        "⚠️ Need Reorder": 2,
        "✅ Healthy": 3,
        "📈 Good Buffer": 4,
        "🛑 Overstock": 5,
        "📦 New/Dead Stock": 6
    }
    analysis_df['Status_Order'] = analysis_df['Status'].map(status_order)
    
    return analysis_df.sort_values('Status_Order')

# --- MAIN DASHBOARD ---
try:
    # Header dengan gradient premium
    st.markdown("""
    <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                padding: 2rem; 
                border-radius: 15px; 
                margin-bottom: 2rem;
                color: white;">
        <h1 style="color: white; margin: 0; font-size: 2.8rem;">🏭 Supply Chain Command Center</h1>
        <p style="opacity: 0.9; font-size: 1.1rem; margin-top: 0.5rem;">Flagship Store Inventory & Replenishment Dashboard</p>
        <p style="opacity: 0.8; font-size: 0.9rem; margin-top: 0.2rem;">Last Updated: """ + datetime.now().strftime("%d %b %Y, %H:%M") + """</p>
    </div>
    """, unsafe_allow_html=True)
    
    # Load data dengan spinner yang elegan
    with st.spinner("🔄 Loading real-time data from Google Sheets..."):
        df_sales, df_kamus, df_stock = load_data()
    
    if df_sales.empty or df_stock.empty:
        st.error("❌ Data tidak dapat dimuat. Silakan periksa koneksi dan file sumber.")
        st.stop()
    
    # --- DATA PREPARATION ---
    df_sales['Orderdate'] = pd.to_datetime(df_sales['Orderdate'], dayfirst=True, errors='coerce')
    df_sales = df_sales.dropna(subset=['Orderdate'])
    
    # Mapping store code
    df_sales['POS_Code'] = df_sales['Ordernumber'].astype(str).str[:4]
    df_sales_mapped = pd.merge(df_sales, df_kamus, left_on='POS_Code', right_on='POS', how='left')
    
    # --- SIDEBAR FILTER PROFESIONAL ---
    with st.sidebar:
        st.markdown("### ⚙️ Dashboard Configuration")
        
        # Date Range Filter
        st.markdown("**📅 Date Range**")
        col1, col2 = st.columns(2)
        with col1:
            start_date = st.date_input("From", 
                                     value=datetime.now() - timedelta(days=90),
                                     key="start_date")
        with col2:
            end_date = st.date_input("To", 
                                   value=datetime.now(),
                                   key="end_date")
        
        # Store Selection
        st.markdown("**🏪 Store Selection**")
        store_options = ["All Stores"] + sorted(df_stock['Store_Name'].dropna().unique().tolist())
        selected_stores = st.multiselect(
            "Select Stores:",
            options=store_options[1:],
            default=store_options[1:] if len(store_options) > 1 else []
        )
        
        if not selected_stores:
            selected_stores = store_options[1:]
        
        # Status Filter
        st.markdown("**📊 Stock Status Filter**")
        status_options = ["🚨 Critical", "⚠️ Need Reorder", "✅ Healthy", "📈 Good Buffer", "🛑 Overstock", "📦 New/Dead Stock"]
        selected_status = st.multiselect(
            "Show statuses:",
            options=status_options,
            default=status_options
        )
        
        # Threshold Settings
        st.markdown("**⚡ Alert Thresholds**")
        reorder_threshold = st.slider("Reorder Threshold (months)", 0.5, 2.0, 1.0, 0.1)
        overstock_threshold = st.slider("Overstock Threshold (months)", 2.0, 6.0, 3.0, 0.5)
    
    # Filter data berdasarkan pilihan store
    stock_filtered = df_stock[df_stock['Store_Name'].isin(selected_stores)] if selected_stores else df_stock
    sales_filtered = df_sales_mapped[df_sales_mapped['Store_Name'].isin(selected_stores)] if selected_stores else df_sales_mapped
    
    # --- KPI CARDS ---
    st.markdown("### 📈 Executive Summary")
    
    # Hitung metrics utama
    analysis_df = calculate_stock_health(stock_filtered, sales_filtered)
    
    if not analysis_df.empty:
        total_stock_value = analysis_df['Stock_Value'].sum()
        total_skus = analysis_df['SKU'].nunique()
        
        # Hitung distribusi status
        status_counts = analysis_df['Status'].value_counts()
        critical_count = status_counts.get("🚨 Critical", 0)
        reorder_count = status_counts.get("⚠️ Need Reorder", 0)
        healthy_count = status_counts.get("✅ Healthy", 0) + status_counts.get("📈 Good Buffer", 0)
        
        total_items = status_counts.sum()
        health_percentage = (healthy_count / total_items * 100) if total_items > 0 else 0
        
        # Display KPI Cards
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.markdown(f"""
            <div class="metric-card">
                <div class="metric-title">Total Stock Value</div>
                <div class="metric-value">Rp {total_stock_value:,.0f}</div>
                <div class="metric-change">{total_skus} SKUs Active</div>
            </div>
            """, unsafe_allow_html=True)
        
        with col2:
            st.markdown(f"""
            <div class="metric-card">
                <div class="metric-title">Stock Health Score</div>
                <div class="metric-value">{health_percentage:.1f}%</div>
                <div class="metric-change">{healthy_count} of {total_items} SKUs</div>
            </div>
            """, unsafe_allow_html=True)
        
        with col3:
            st.markdown(f"""
            <div class="metric-card">
                <div class="metric-title">Require Attention</div>
                <div class="metric-value">{critical_count + reorder_count}</div>
                <div class="metric-change">SKUs Need Action</div>
            </div>
            """, unsafe_allow_html=True)
        
        with col4:
            avg_cover = analysis_df[analysis_df['Month_Cover'] < 50]['Month_Cover'].median()
            st.markdown(f"""
            <div class="metric-card">
                <div class="metric-title">Avg. Month Cover</div>
                <div class="metric-value">{avg_cover:.1f}x</div>
                <div class="metric-change">Inventory Buffer</div>
            </div>
            """, unsafe_allow_html=True)
    
    # --- TABBED INTERFACE ---
    tab1, tab2, tab3, tab4 = st.tabs(["📊 Store Overview", "🚨 Priority Actions", "📦 Stock Analysis", "📈 Trends & Forecast"])
    
    with tab1:
        st.markdown("### 🏪 Store Performance Summary")
        
        if not analysis_df.empty:
            # Group by store analysis
            store_summary = analysis_df.groupby('Store_Name').agg({
                'SKU': 'nunique',
                'Total': 'sum',
                'Stock_Value': 'sum',
                'Month_Cover': 'median',
                'Status': lambda x: (x.isin(['✅ Healthy', '📈 Good Buffer'])).sum() / len(x) * 100
            }).round(2).reset_index()
            
            store_summary.columns = ['Store', 'SKU Count', 'Total Units', 'Stock Value', 'Avg Month Cover', 'Health %']
            
            # Display store cards
            cols = st.columns(len(store_summary))
            for idx, (col, (_, row)) in enumerate(zip(cols, store_summary.iterrows())):
                with col:
                    health_color = "#10B981" if row['Health %'] > 70 else "#F59E0B" if row['Health %'] > 40 else "#EF4444"
                    st.markdown(f"""
                    <div class="store-card">
                        <h4 style="margin: 0 0 10px 0;">{row['Store']}</h4>
                        <div style="display: flex; justify-content: space-between; margin-bottom: 5px;">
                            <span style="font-size: 0.9rem; opacity: 0.7;">SKUs:</span>
                            <span style="font-weight: 600;">{int(row['SKU Count'])}</span>
                        </div>
                        <div style="display: flex; justify-content: space-between; margin-bottom: 5px;">
                            <span style="font-size: 0.9rem; opacity: 0.7;">Units:</span>
                            <span style="font-weight: 600;">{int(row['Total Units']):,}</span>
                        </div>
                        <div style="display: flex; justify-content: space-between; margin-bottom: 5px;">
                            <span style="font-size: 0.9rem; opacity: 0.7;">Health:</span>
                            <span style="font-weight: 600; color: {health_color};">{row['Health %']:.1f}%</span>
                        </div>
                        <div style="margin-top: 10px; background: #f3f4f6; border-radius: 5px; padding: 5px;">
                            <div style="font-size: 0.8rem; opacity: 0.7;">Avg. Cover:</div>
                            <div style="font-weight: 700; font-size: 1.2rem;">{row['Avg Month Cover']:.1f}x</div>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
            
            # Store comparison chart
            st.markdown("#### Store Comparison")
            col1, col2 = st.columns(2)
            
            with col1:
                fig1 = px.bar(store_summary, x='Store', y='Health %',
                            title='Stock Health by Store',
                            color='Health %',
                            color_continuous_scale='RdYlGn')
                fig1.update_layout(height=300)
                st.plotly_chart(fig1, use_container_width=True)
            
            with col2:
                fig2 = px.pie(analysis_df, names='Status', 
                            title='Overall Stock Status Distribution',
                            hole=0.4)
                fig2.update_layout(height=300)
                st.plotly_chart(fig2, use_container_width=True)
    
    with tab2:
        st.markdown("### 🚨 Priority Action Items")
        
        # Filter SKUs yang butuh perhatian
        priority_items = analysis_df[analysis_df['Status'].isin(['🚨 Critical', '⚠️ Need Reorder'])]
        
        if not priority_items.empty:
            # Group by store untuk reorder recommendations
            for store in priority_items['Store_Name'].unique():
                store_items = priority_items[priority_items['Store_Name'] == store]
                
                with st.expander(f"**{store}** - {len(store_items)} SKUs Need Attention", expanded=True):
                    # Calculate recommended order quantity
                    store_items = store_items.copy()
                    store_items['Recommended_Order'] = np.where(
                        store_items['Month_Cover'] < 1,
                        (store_items['AMS'] * 1.5 - store_items['Total']).clip(lower=1),
                        (store_items['AMS'] * 0.5).clip(lower=1)
                    )
                    
                    # Display table
                    display_cols = ['SKU', 'Total', 'AMS', 'Month_Cover', 'Recommended_Order', 'Status']
                    styled_df = store_items[display_cols].sort_values('Month_Cover')
                    
                    # Format untuk display
                    styled_df['Month_Cover'] = styled_df['Month_Cover'].apply(lambda x: f"{x:.1f}x")
                    styled_df['Recommended_Order'] = styled_df['Recommended_Order'].apply(lambda x: f"{int(x)} pcs")
                    styled_df['AMS'] = styled_df['AMS'].apply(lambda x: f"{x:.1f}/month")
                    
                    st.dataframe(
                        styled_df,
                        column_config={
                            "Status": st.column_config.TextColumn(
                                width="small",
                                help="Stock status classification"
                            ),
                            "Month_Cover": st.column_config.NumberColumn(
                                "Cover",
                                help="Current stock divided by monthly sales"
                            )
                        },
                        use_container_width=True,
                        hide_index=True
                    )
                    
                    # Total reorder summary
                    total_reorder = store_items['Recommended_Order'].sum()
                    st.info(f"**Total Recommended Order for {store}: {int(total_reorder):,} units across {len(store_items)} SKUs**")
        else:
            st.success("🎉 No critical items found! All stock levels are within acceptable ranges.")
    
    with tab3:
        st.markdown("### 📦 Detailed Stock Analysis")
        
        # Advanced filtering
        col1, col2, col3 = st.columns(3)
        with col1:
            min_cover = st.number_input("Min Month Cover", 0.0, 50.0, 0.0, 0.5)
        with col2:
            max_cover = st.number_input("Max Month Cover", 0.0, 50.0, 10.0, 0.5)
        with col3:
            min_stock = st.number_input("Min Stock Qty", 0, 1000, 0, 10)
        
        # Filter analysis dataframe
        filtered_analysis = analysis_df[
            (analysis_df['Month_Cover'] >= min_cover) &
            (analysis_df['Month_Cover'] <= max_cover) &
            (analysis_df['Total'] >= min_stock) &
            (analysis_df['Status'].isin(selected_status))
        ]
        
        # Tampilkan dalam tabs untuk masing-masing store
        store_tabs = st.tabs([f"📊 {store}" for store in filtered_analysis['Store_Name'].unique()])
        
        for tab, store in zip(store_tabs, filtered_analysis['Store_Name'].unique()):
            with tab:
                store_data = filtered_analysis[filtered_analysis['Store_Name'] == store]
                
                # Metrics untuk store ini
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Total SKUs", len(store_data))
                with col2:
                    st.metric("Total Units", f"{store_data['Total'].sum():,}")
                with col3:
                    healthy_pct = (store_data['Status'].isin(['✅ Healthy', '📈 Good Buffer'])).sum() / len(store_data) * 100
                    st.metric("Health Score", f"{healthy_pct:.1f}%")
                
                # Interactive data table
                st.dataframe(
                    store_data[['SKU', 'Status', 'Total', 'AMS', 'Month_Cover', 'Stock_Value']].sort_values('Month_Cover'),
                    column_config={
                        "Status": st.column_config.SelectboxColumn(
                            "Status",
                            help="Current stock status",
                            width="small",
                            options=status_options
                        ),
                        "Month_Cover": st.column_config.ProgressColumn(
                            "Month Cover",
                            help="Current stock divided by monthly sales",
                            format="%.1fx",
                            min_value=0,
                            max_value=10
                        ),
                        "Stock_Value": st.column_config.NumberColumn(
                            "Value (Rp)",
                            format="Rp %.0f"
                        )
                    },
                    use_container_width=True,
                    height=400
                )
    
    with tab4:
        st.markdown("### 📈 Sales Trends & Forecast")
        
        # Sales trend analysis
        if not sales_filtered.empty:
            # Monthly sales trend
            sales_filtered['Month'] = sales_filtered['Orderdate'].dt.to_period('M')
            monthly_sales = sales_filtered.groupby('Month').agg({
                'ItemOrdered': 'sum',
                'ItemPrice': lambda x: (x * sales_filtered.loc[x.index, 'ItemOrdered']).sum() / sales_filtered.loc[x.index, 'ItemOrdered'].sum()
            }).reset_index()
            
            monthly_sales['Month'] = monthly_sales['Month'].dt.to_timestamp()
            monthly_sales['Revenue'] = monthly_sales['ItemOrdered'] * monthly_sales['ItemPrice']
            
            # Plot trend
            fig = make_subplots(specs=[[{"secondary_y": True}]])
            
            fig.add_trace(
                go.Scatter(x=monthly_sales['Month'], y=monthly_sales['ItemOrdered'],
                          name="Units Sold", line=dict(color='#3B82F6', width=3)),
                secondary_y=False,
            )
            
            fig.add_trace(
                go.Bar(x=monthly_sales['Month'], y=monthly_sales['Revenue'],
                      name="Revenue", marker_color='#10B981', opacity=0.6),
                secondary_y=True,
            )
            
            fig.update_layout(
                title="Monthly Sales Trend",
                hovermode="x unified",
                height=400
            )
            
            fig.update_yaxes(title_text="Units Sold", secondary_y=False)
            fig.update_yaxes(title_text="Revenue (Rp)", secondary_y=True)
            
            st.plotly_chart(fig, use_container_width=True)
            
            # Forecast kebutuhan stock
            st.markdown("#### 📊 Stock Cover Analysis by Store")
            
            # Hitung stock cover per store
            cover_by_store = analysis_df.groupby('Store_Name').agg({
                'Month_Cover': ['mean', 'median', 'min', 'max']
            }).round(2)
            
            cover_by_store.columns = ['Avg Cover', 'Median Cover', 'Min Cover', 'Max Cover']
            st.dataframe(cover_by_store, use_container_width=True)
            
            # Heatmap of stock status by store
            pivot_data = analysis_df.pivot_table(
                index='Store_Name',
                columns='Status',
                values='SKU',
                aggfunc='count',
                fill_value=0
            )
            
            if not pivot_data.empty:
                fig_heat = px.imshow(pivot_data,
                                   labels=dict(x="Status", y="Store", color="SKU Count"),
                                   title="Stock Status Distribution by Store",
                                   color_continuous_scale='RdYlGn')
                fig_heat.update_layout(height=400)
                st.plotly_chart(fig_heat, use_container_width=True)
    
    # --- FOOTER DAN DOWNLOAD ---
    st.markdown("---")
    col1, col2 = st.columns([3, 1])
    
    with col1:
        st.caption(f"Dashboard updated: {datetime.now().strftime('%d %b %Y %H:%M:%S')} | Data source: Google Sheets")
    
    with col2:
        if not analysis_df.empty:
            csv = analysis_df.to_csv(index=False).encode('utf-8')
            st.download_button(
                "📥 Download Full Report",
                csv,
                f"supply_chain_report_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                "text/csv",
                use_container_width=True
            )

except Exception as e:
    st.error(f"❌ An error occurred: {str(e)}")
    
    # Debug information (collapsed)
    with st.expander("⚠️ Technical Details (for debugging)"):
        import traceback
        st.code(traceback.format_exc())
