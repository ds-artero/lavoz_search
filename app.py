import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
from urllib.parse import urljoin
from collections import defaultdict, OrderedDict
import plotly.express as px 
import re
from datetime import datetime, date, timedelta
from dateutil.relativedelta import relativedelta
import io

# --- Configuration and Core Scraping Functions ---

DOMAIN = "https://www.lavozdegalicia.es"
SEARCH_ENDPOINT = "https://www.lavozdegalicia.es/buscador/q/"
DEFAULT_PAGE_SIZE = 10

# --- Helper: Name Variations ---
def get_search_variations(name_input):
    """Generates variations of a name to broaden search."""
    name_input = name_input.strip()
    variations = [name_input] 
    
    parts = name_input.split()
    if len(parts) >= 2:
        first_name = parts[0]
        surname = " ".join(parts[1:]) 
        
        # Variation 1: Initial + Surname (e.g., "C. ZAPATER")
        initial_var = f"{first_name[0]}. {surname}"
        if initial_var not in variations:
            variations.append(initial_var)
            
        # Variation 2: Surname only (e.g., "ZAPATER")
        if surname not in variations:
            variations.append(surname)
            
    return variations

# --- Helper: Fiscal Month Calculator ---
def calculate_fiscal_month(date_obj):
    """
    Determines the 'Fiscal Month' (YYYY-MM) based on the 16th-15th rule.
    """
    try:
        if pd.isna(date_obj):
            return None
            
        if date_obj.day > 15:
            # Belongs to next month
            adjusted_date = date_obj + relativedelta(months=1)
        else:
            # Belongs to current month
            adjusted_date = date_obj
            
        return adjusted_date.strftime('%Y-%m')
    except:
        return None

# --- Date Parsing Helper ---
@st.cache_data
def parse_date_and_normalize(date_str):
    """Parses Spanish date strings."""
    date_str = date_str.strip()
    spanish_months = {
        'enero': 1, 'febrero': 2, 'marzo': 3, 'abril': 4, 'mayo': 5, 'junio': 6,
        'julio': 7, 'agosto': 8, 'septiembre': 9, 'octubre': 10, 'noviembre': 11, 'diciembre': 12
    }
    match = re.search(r'(\d+)\s+de\s+(\w+)\s+de\s+(\d{4})', date_str, re.IGNORECASE)
    if match:
        try:
            day = int(match.group(1))
            month_name = match.group(2).lower()
            year = int(match.group(3))
            month_num = spanish_months.get(month_name)
            if month_num:
                return f"{year}-{month_num:02d}-{day:02d}"
        except Exception:
            pass
            
    if any(keyword in date_str.lower() for keyword in ['hoy', 'ayer', 'hora', 'minuto']):
        return datetime.now().strftime('%Y-%m-%d')
            
    return date_str

# --- Data Summarization and Plotting ---

@st.cache_data
def summarize_by_group(df):
    if df.empty or 'MONTH_GROUP' not in df.columns:
        return pd.DataFrame({'Month': [], 'Count': []})
            
    monthly_counts = df['MONTH_GROUP'].value_counts().sort_index()
    summary_df = pd.DataFrame({'Month': monthly_counts.index, 'Count': monthly_counts.values})
    return summary_df

@st.cache_data
def create_monthly_plot_plotly(summary_df, search_term):
    """Creates a Plotly bar chart with PINK and PURPLE theme."""
    if summary_df.empty:
        return None
    
    average_count = summary_df['Count'].mean()
        
    fig = px.bar(
        summary_df,
        x='Month',
        y='Count',
        text='Count',
        title=f"<b>Artículos 2025 por Mes Fiscal</b><br><span style='font-size: 12px; color: purple;'>Búsqueda: {search_term}</span>",
        labels={
            "Count": "Artículos",
            "Month": "Mes Fiscal"
        },
        # --- THEME: PINK BAR ---
        color_discrete_sequence=['#E91E63']  # Deep Pink
    )
    
    # --- THEME: PURPLE AVERAGE LINE ---
    fig.add_hline(
        y=average_count,
        line_dash="dash",
        line_color="#9C27B0", # Purple
        line_width=3,
        annotation_text=f"<b>Promedio: {average_count:.2f}</b>",
        annotation_position="top right",
        annotation_font_color="#9C27B0"
    )
    
    fig.update_traces(
        textposition='outside',
        marker_line_color='#880E4F', # Darker Pink Border
        marker_line_width=2, 
        opacity=0.85
    )
    
    fig.update_layout(
        xaxis={'categoryorder':'category ascending'},
        hovermode="x unified",
        plot_bgcolor="rgba(0,0,0,0)", # Transparent background
        yaxis_title="Número de Artículos",
        height=500,
        title_font_color="#880E4F",
        font=dict(family="Arial", size=12, color="#4A148C") # Purple text
    )
    
    return fig

# --- Main Scraping Logic ---

def scrape_lavoz_recursive(search_variations, max_page=5, page_size=DEFAULT_PAGE_SIZE, progress_bar=None, status_text=None):
    """
    Scrapes articles with UTF-8 enforcement and strict cleaning.
    """
    all_articles_data = []
    unique_links = set() 
    
    base_form_data = {
        'pageSize': str(page_size),
        'sort': 'D0003_FECHAPUBLICACION desc',
        'doctype': '', 'dateFrom': '', 'dateTo': '', 'edicion': '',
        'formato': '', 'seccion': '', 'blog': '', 'autor': '',
        'source': 'info',
    }
    
    total_steps = len(search_variations) * max_page
    current_step = 0

    for term in search_variations:
        base_form_data['text'] = term 
        
        if status_text:
            status_text.markdown(f"🌸 Buscando variante: **'{term}'**...")

        for page_num in range(1, max_page + 1):
            current_step += 1
            if progress_bar:
                progress_bar.progress(current_step / total_steps)

            form_data = base_form_data.copy()
            form_data['pageNumber'] = str(page_num) 

            try:
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                    'Referer': SEARCH_ENDPOINT 
                }
                response = requests.post(SEARCH_ENDPOINT, headers=headers, data=form_data, timeout=10)
                
                # --- CRITICAL FIX: Force UTF-8 Encoding ---
                response.encoding = 'utf-8' 
                
                response.raise_for_status()

                soup = BeautifulSoup(response.text, 'html.parser')
                article_containers = soup.select('article') 
                
                if not article_containers:
                    break
                    
                for container in article_containers:
                    link_tag = container.select_one('h1 a[href]')
                    if not (link_tag and link_tag.get('href')):
                        continue 
                    
                    article_url = urljoin(DOMAIN, link_tag.get('href'))
                    
                    if article_url in unique_links:
                        continue

                    title = link_tag.get_text(strip=True)
                    
                    date_tag = container.select_one('time.entry-date')
                    date_raw = date_tag.get_text(strip=True) if date_tag else 'Date Not Found'
                    
                    # Prefer datetime attribute if available
                    if date_tag and date_tag.has_attr('datetime'):
                         if len(date_tag['datetime']) > 5:
                             date_raw = date_tag['datetime']

                    normalized_date = parse_date_and_normalize(date_raw)

                    unique_links.add(article_url)
                    all_articles_data.append({
                        'TITLE': title,
                        'DATE_NORMALIZED': normalized_date,
                        'DATE_RAW': date_raw,
                        'URL': article_url,
                        'FOUND_VIA': term 
                    })
            
                time.sleep(0.5) 

            except requests.exceptions.RequestException as e:
                st.error(f"Error: {e}")
                break
        
    return pd.DataFrame(all_articles_data)


# --- Streamlit Application Layout ---

st.set_page_config(layout="wide", page_title="La Voz Monitor 2025")

# --- CSS Injection for Pink/Purple Theme ---
st.markdown("""
    <style>
    .main-title {
        color: #E91E63;
        font-size: 3em;
        font-weight: bold;
    }
    .sub-header {
        color: #9C27B0;
        font-weight: bold;
    }
    /* Customize dataframe headers slightly if possible via simple CSS */
    [data-testid="stDataFrame"] div[data-testid="stVerticalBlock"] {
        border-top: 2px solid #E91E63;
    }
    </style>
""", unsafe_allow_html=True)

st.markdown('<div class="main-title">📰 Artículos en La Voz )</div>', unsafe_allow_html=True)
st.markdown("**Ahora, en rosa xd.** El sistema busca variantes y agrupa por mes fiscal (16-15).")

# --- Sidebar ---
st.sidebar.header("🔍 Configuración")
search_input = st.sidebar.text_input("TÉRMINO A BUSCAR", value="CLAUDIA ZAPATER")
max_pages = st.sidebar.slider("Páginas máx. por variante", 1, 10, 5)

# --- Search Logic ---
if 'df_results' not in st.session_state:
    st.session_state['df_results'] = pd.DataFrame()

if st.sidebar.button("🌺 BUSCAR", type="primary"):
    
    variations = get_search_variations(search_input)
    
    st.markdown(f"<h3 class='sub-header'>⏳ Buscando variantes: {', '.join(variations)}...</h3>", unsafe_allow_html=True)
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    df_raw = scrape_lavoz_recursive(
        variations, 
        max_pages, 
        progress_bar=progress_bar, 
        status_text=status_text
    )
    
    # --- FILTER: STRICTLY 2025 AND BEYOND ---
    if not df_raw.empty:
        # Ensure datetime
        df_raw['DATE_OBJ'] = pd.to_datetime(df_raw['DATE_NORMALIZED'], errors='coerce')
        df_raw.dropna(subset=['DATE_OBJ'], inplace=True)
        
        # Apply 2025 Filter
        df_2025 = df_raw[df_raw['DATE_OBJ'] >= '2025-01-01'].copy()
        
        st.session_state['df_results'] = df_2025
    else:
        st.session_state['df_results'] = pd.DataFrame()
    
    progress_bar.empty()
    
    count = len(st.session_state['df_results'])
    if count > 0:
        status_text.markdown(f"✅ **¡Éxito!** Encontrados **{count}** artículos de 2025.")
    else:
        status_text.warning("⚠️ Se completó la búsqueda pero no se encontraron artículos en 2025.")

# --- Results Display ---
df_results = st.session_state['df_results']

if not df_results.empty:
    
    # Calculate Fiscal Month
    df_results['MONTH_GROUP'] = df_results['DATE_OBJ'].apply(calculate_fiscal_month)
    
    # --- FILTERS SIDEBAR ---
    st.sidebar.markdown("---")
    st.sidebar.markdown("[**📅 Filtros Adicionales**]")
    
    # Group Month Filter
    available_months = sorted(df_results['MONTH_GROUP'].dropna().unique(), reverse=True)
    selected_months = st.sidebar.multiselect(
        "Filtrar por Mes Fiscal",
        options=available_months,
        default=available_months
    )
    
    # Apply Filters
    mask = (df_results['MONTH_GROUP'].isin(selected_months))
    df_filtered = df_results[mask].copy()

    if df_filtered.empty:
        st.warning("No hay resultados con los filtros seleccionados.")
    else:
        # --- Section 1: Data Table ---
        st.markdown("<h3 class='sub-header'>📊 Tabla Detallada</h3>", unsafe_allow_html=True)
        
        display_cols = ['TITLE', 'DATE_NORMALIZED', 'MONTH_GROUP', 'URL']
        
        st.dataframe(
            df_filtered[display_cols], 
            use_container_width=True, 
            hide_index=True,
            column_config={
                "URL": st.column_config.LinkColumn("Enlace"),
                "MONTH_GROUP": st.column_config.TextColumn("Mes Fiscal (16-15)"),
                "TITLE": st.column_config.TextColumn("Titular"),
                "DATE_NORMALIZED": st.column_config.DateColumn("Fecha")
            }
        )

        # --- Section 2: Summary & Plot ---
        summary_df = summarize_by_group(df_filtered)
        
        col1, col2 = st.columns([1, 2])
        
        with col1:
            st.markdown(":purple[**Resumen Numérico**]")
            st.dataframe(
                summary_df.sort_values(by='Month', ascending=False), 
                use_container_width=True, 
                hide_index=True
            )
            
        with col2:
            st.markdown(":purple[**Visualización**]")
            fig_plotly = create_monthly_plot_plotly(summary_df, search_input)
            if fig_plotly:
                st.plotly_chart(fig_plotly, use_container_width=True)

        # --- Section 3: Download ---
        st.markdown("---")
        csv_buffer = io.StringIO()
        df_filtered.to_csv(csv_buffer, index=False)
        st.download_button(
            label="💜 Descargar CSV (Resultados Filtrados)",
            data=csv_buffer.getvalue(),
            file_name=f'reporte_2025_{search_input.replace(" ", "_")}.csv',
            mime='text/csv',
            type="primary" # Makes the button stand out (usually red/pink in standard theme)
        )
        
else:
    st.info("💜 Ingresa un nombre en la barra lateral para comenzar.")
