import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
from urllib.parse import urljoin
from collections import defaultdict, OrderedDict
import matplotlib.pyplot as plt
import re
from datetime import datetime
from dateutil.relativedelta import relativedelta
import io
from matplotlib.backends.backend_pdf import PdfPages

# --- Configuration and Core Scraping Functions ---

DOMAIN = "https://www.lavozdegalicia.es"
SEARCH_ENDPOINT = "https://www.lavozdegalicia.es/buscador/q/"
DEFAULT_PAGE_SIZE = 10 

# --- Date Parsing Helper ---
@st.cache_data
def parse_date_and_normalize(date_str):
    """Parses Spanish date strings (e.g., '18 de julio de 2025') into YYYY-MM-DD."""
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
            
    # Fallback for relative dates (we use today's date)
    if any(keyword in date_str.lower() for keyword in ['hoy', 'ayer', 'hora', 'minuto']):
        return datetime.now().strftime('%Y-%m-%d')
        
    return date_str 

# --- Data Summarization and Plotting ---

@st.cache_data
def summarize_by_month(df):
    """
    Processes DataFrame and summarizes the count by YYYY-MM, 
    where a month runs from the 16th to the 15th of the next month.
    """
    if df.empty:
        return pd.DataFrame({'Month': [], 'Count': []})
        
    monthly_counts = defaultdict(int)
    
    for date_str in df['DATE_NORMALIZED']:
        if re.match(r'\d{4}-\d{2}-\d{2}', date_str):
            try:
                date_obj = datetime.strptime(date_str, '%Y-%m-%d')
                
                # --- NEW LOGIC: 16th to 15th Period ---
                if date_obj.day > 15:
                    # If date is 16th or later, it belongs to the NEXT month's period
                    # Use relativedelta to reliably add one month, handling year end
                    adjusted_date = date_obj + relativedelta(months=1)
                else:
                    # If date is 15th or earlier, it belongs to the CURRENT month's period
                    adjusted_date = date_obj 
                
                # The month key is based on the ADJUSTED month (the month the period is named after)
                month_key = adjusted_date.strftime('%Y-%m')
                monthly_counts[month_key] += 1
                
            except ValueError:
                # Handle cases where DATE_NORMALIZED is not a valid date string
                pass

    sorted_items = OrderedDict(sorted(monthly_counts.items()))
    
    summary_df = pd.DataFrame(list(sorted_items.items()), columns=['Month', 'Count'])
    return summary_df

@st.cache_data
def create_monthly_plot(summary_df, search_term):
    """Creates a Matplotlib bar chart of article count vs. month/year."""
    if summary_df.empty:
        # Create an empty figure to prevent errors
        fig, ax = plt.subplots(figsize=(12, 6))
        ax.text(0.5, 0.5, "No data available for plotting.", horizontalalignment='center', verticalalignment='center', transform=ax.transAxes)
        ax.axis('off')
        return fig
        
    months = summary_df['Month']
    counts = summary_df['Count']
    
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.bar(months, counts, color='#0079c1') 
    
    ax.set_xlabel("Month/Year (Period runs 16th to 15th)")
    ax.set_ylabel("Number of Unique Articles")
    ax.set_title(f"La Voz de Galicia: Article Count for '{search_term}'", fontsize=16)
    ax.tick_params(axis='x', rotation=45)
    ax.grid(axis='y', linestyle='--', alpha=0.7)
    
    # Add count values on top of the bars
    for i, count in enumerate(counts):
        ax.text(i, count + 0.5, str(count), ha='center', va='bottom', fontsize=9)
    
    plt.tight_layout()
    return fig

# --- Main Scraping Logic (Adapted for Streamlit) ---

def scrape_lavoz_main_search_post(search_text, max_page=5, page_size=DEFAULT_PAGE_SIZE, progress_bar=None, status_text=None):
    """
    Scrapes articles from the main La Voz de Galicia search page using POST requests.
    """
    all_articles_data = []
    unique_links = set() 
    
    base_form_data = {
        'text': search_text,
        'pageSize': str(page_size),
        'sort': 'D0003_FECHAPUBLICACION desc',
        'doctype': '', 'dateFrom': '', 'dateTo': '', 'edicion': '',
        'formato': '', 'seccion': '', 'blog': '', 'autor': '',
        'source': 'info',
    }
    
    articles_found = 0

    for page_num in range(1, max_page + 1):
        
        if status_text:
            status_text.text(f"Fetching page {page_num}/{max_page}...")

        form_data = base_form_data.copy()
        form_data['pageNumber'] = str(page_num) 

        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Referer': SEARCH_ENDPOINT 
            }
            response = requests.post(SEARCH_ENDPOINT, headers=headers, data=form_data, timeout=10)
            response.raise_for_status()

            soup = BeautifulSoup(response.content, 'html.parser')
            
            article_containers = soup.select('article') 
            
            if not article_containers:
                break
                
            for container in article_containers:
                
                link_tag = container.select_one('h1 a[href]')
                if not (link_tag and link_tag.get('href')):
                    continue 
                
                article_url = urljoin(DOMAIN, link_tag.get('href'))
                title = link_tag.get_text(strip=True)
                
                date_tag = container.select_one('time.entry-date')
                date_raw = date_tag.get('datetime', 'Date Not Found') if date_tag else 'Date Not Found'
                normalized_date = parse_date_and_normalize(date_raw)

                if article_url not in unique_links:
                    unique_links.add(article_url)
                    all_articles_data.append({
                        'TITLE': title,
                        'DATE_NORMALIZED': normalized_date,
                        'DATE_RAW': date_raw,
                        'URL': article_url,
                    })
                    articles_found += 1
            
            time.sleep(1.0) # Be polite

        except requests.exceptions.RequestException as e:
            st.error(f"Error fetching page {page_num}: {e}")
            break
            
        if progress_bar:
             progress_bar.progress(page_num / max_page)
        
    return pd.DataFrame(all_articles_data)

def generate_pdf_report(df_results, fig, search_term):
    """Generates the PDF file containing the plot and the data table."""
    pdf_buffer = io.BytesIO()
    
    with PdfPages(pdf_buffer, keep_empty=False) as pdf:
        # Add Graph to PDF
        pdf.savefig(fig)
        
        # Add Data Table to PDF
        fig_table, ax_table = plt.subplots(figsize=(10, 0.5 + len(df_results.index) * 0.3)) # Dynamic height
        ax_table.axis('off')
        ax_table.axis('tight')
        ax_table.set_title(f"Scraped Articles for {search_term}", y=1.08)
        
        pdf_table_data = df_results[['TITLE', 'DATE_NORMALIZED', 'URL']].copy()
        pdf_table_data['TITLE'] = pdf_table_data['TITLE'].str.slice(0, 50) + '...'
        
        table = ax_table.table(
            cellText=pdf_table_data.values, 
            colLabels=pdf_table_data.columns, 
            cellLoc='left', 
            loc='center'
        )
        table.auto_set_font_size(False)
        table.set_fontsize(8)
        table.scale(1, 1.2)
        
        pdf.savefig(fig_table)
        plt.close(fig_table)
        plt.close(fig) # Close the Matplotlib figure
            
    return pdf_buffer.getvalue()

# --- Streamlit Application Layout ---

st.set_page_config(layout="wide", page_title="La Voz de Galicia Search Scraper")

st.title("📰 Resumen de tus Artículos en La Voz de Galicia" )
st.markdown("Busca tu nombre! Y tendrás el resumen. **Los meses están calculados como 16-15 de cada mes: Ej: Octubre (16 Oct - 15 Nov).**")

st.sidebar.header("🔍 Search Configuration")
search_term = st.sidebar.text_input("NOMBRE A BUSCAR", value="CLAUDIA ZAPATER")
max_pages = st.sidebar.slider("Maximum Pages to Scan (10 items/page)", 1, 30, 10)

if st.sidebar.button("Run Scraper", type="primary"):
    
    st.header("⏳ Scraping Results")
    st.info(f"Searching for: **{search_term}** across **{max_pages}** pages...")
    
    # Placeholders for live progress
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    # Run the scraper
    df_results = scrape_lavoz_main_search_post(
        search_term, 
        max_pages, 
        progress_bar=progress_bar, 
        status_text=status_text
    )
    
    progress_bar.empty()
    status_text.success(f"✅ Scraping complete! Found {len(df_results)} unique articles.")
    
    if df_results.empty:
        st.warning("No articles were found matching your search criteria.")
    else:
        
        # --- Section 1: Data Table ---
        st.subheader(f"📊 Scraped Articles ({len(df_results)} Total)")
        st.dataframe(df_results, use_container_width=True)

        # --- Section 2: Summary Table ---
        summary_df = summarize_by_month(df_results)
        st.subheader("🗓️ Article Summary per Month (16th-to-15th Period)")
        st.dataframe(summary_df.sort_values(by='Month', ascending=False), use_container_width=True)

        # --- Section 3: Visualization ---
        st.subheader("📈 Monthly Publication Graph")
        fig = create_monthly_plot(summary_df, search_term)
        st.pyplot(fig)
        
        # --- Section 4: Downloads ---
        st.subheader("⬇️ Download Options")
        
        col1, col2 = st.columns(2)

        # CSV Download
        csv_buffer = io.StringIO()
        df_results.to_csv(csv_buffer, index=False)
        col1.download_button(
            label="Download Data as CSV",
            data=csv_buffer.getvalue(),
            file_name=f'lavoz_{search_term.replace(" ", "_").lower()}_articles.csv',
            mime='text/csv'
        )
        
        # PDF Download
        pdf_data = generate_pdf_report(df_results, fig, search_term)
        col2.download_button(
            label="Download Report as PDF (Graph + Table)",
            data=pdf_data,
            file_name=f'lavoz_{search_term.replace(" ", "_").lower()}_report.pdf',
            mime='application/pdf'
        )
