import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
from urllib.parse import urljoin
from collections import defaultdict, OrderedDict
import matplotlib.pyplot as plt
import re
from datetime import datetime
import csv
import io
from matplotlib.backends.backend_pdf import PdfPages

# --- Configuration and Core Scraping Functions ---

DOMAIN = "https://www.lavozdegalicia.es"
SEARCH_ENDPOINT = "https://www.lavozdegalicia.es/buscador/q/"
DEFAULT_PAGE_SIZE = 10 

# --- Date Parsing Helper ---
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
            
    if any(keyword in date_str.lower() for keyword in ['hoy', 'ayer', 'hora', 'minuto']):
        return datetime.now().strftime('%Y-%m-%d')
        
    return date_str 

# --- Data Summarization and Plotting ---

def summarize_by_month(df):
    """Processes DataFrame and summarizes the count by YYYY-MM."""
    if df.empty:
        return pd.DataFrame({'Month': [], 'Count': []})
        
    monthly_counts = defaultdict(int)
    for date_str in df['DATE_NORMALIZED']:
        if re.match(r'\d{4}-\d{2}-\d{2}', date_str):
            month_key = date_str[:7] # YYYY-MM
            monthly_counts[month_key] += 1
            
    sorted_items = OrderedDict(sorted(monthly_counts.items()))
    
    summary_df = pd.DataFrame(list(sorted_items.items()), columns=['Month', 'Count'])
    return summary_df

def create_monthly_plot(summary_df, search_term):
    """Creates a Matplotlib bar chart of article count vs. month/year."""
    if summary_df.empty:
        return None
        
    months = summary_df['Month']
    counts = summary_df['Count']
    
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.bar(months, counts, color='#0079c1') 
    
    ax.set_xlabel("Month/Year")
    ax.set_ylabel("Number of Unique Articles")
    ax.set_title(f"La Voz de Galicia: Article Count for '{search_term}'", fontsize=16)
    ax.tick_params(axis='x', rotation=45)
    ax.grid(axis='y', linestyle='--', alpha=0.7)
    
    for i, count in enumerate(counts):
        ax.text(i, count + 0.5, str(count), ha='center', va='bottom', fontsize=9)
    
    plt.tight_layout()
    return fig

def generate_output_files(df_results, monthly_summary_df, fig, search_term):
    """Generates the CSV and PDF files."""
    
    base_filename = f'lavoz_{search_term.replace(" ", "_").lower()}'

    # 1. Generate CSV File
    csv_filename = f'{base_filename}_articles.csv'
    df_results.to_csv(csv_filename, index=False, encoding='utf-8')
    print(f"\n✅ CSV file generated: {csv_filename}")
    
    # 2. Generate PDF Report
    pdf_filename = f'{base_filename}_report.pdf'
    
    # Create the PDF file with the plot and data table
    with PdfPages(pdf_filename) as pdf:
        
        # Save the Graph
        pdf.savefig(fig)
        
        # Save the Data Table
        # We create a new figure for the table to handle dynamic size
        fig_table, ax_table = plt.subplots(figsize=(10, 1 + len(df_results.index) * 0.3)) 
        ax_table.axis('off')
        ax_table.axis('tight')
        ax_table.set_title(f"Article Data for {search_term}", y=1.05)
        
        # Prepare data for plotting table (only key columns)
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

    print(f"✅ PDF report generated: {pdf_filename}")
    plt.close(fig) # Close the plot after saving
    
    return csv_filename, pdf_filename

# --- Main Scraping Logic (Optimized for POST Request) ---

def scrape_lavoz_main_search_post(search_text, max_page=5, page_size=DEFAULT_PAGE_SIZE):
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

    for page_num in range(1, max_page + 1):
        
        print(f"--- Fetching page: {page_num} of {max_page} ---")

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
            
            # CONFIRMED SELECTOR
            article_containers = soup.select('article') 
            
            if not article_containers:
                print("No more articles found. Stopping.")
                break
                
            articles_added = 0
            for container in article_containers:
                
                # 1. Title and URL Extraction
                link_tag = container.select_one('h1 a[href]')
                if not (link_tag and link_tag.get('href')):
                    continue 
                
                article_url = urljoin(DOMAIN, link_tag.get('href'))
                title = link_tag.get_text(strip=True)
                
                # 2. Date Extraction
                date_tag = container.select_one('time.entry-date')
                date_raw = date_tag.get('datetime', 'Date Not Found') if date_tag else 'Date Not Found'
                normalized_date = parse_date_and_normalize(date_raw)

                # 3. Deduplication and Storage
                if article_url not in unique_links:
                    unique_links.add(article_url)
                    all_articles_data.append({
                        'TITLE': title,
                        'DATE_NORMALIZED': normalized_date,
                        'DATE_RAW': date_raw,
                        'URL': article_url,
                    })
                    articles_added += 1
            
            print(f"-> Added {articles_added} unique articles. Total: {len(all_articles_data)}")
            
            time.sleep(1.0) 

        except requests.exceptions.RequestException as e:
            print(f"Error fetching page {page_num}: {e}. Stopping scrape.")
            break
        
    return pd.DataFrame(all_articles_data)

# --- Colab Execution Block ---

# 1. Configuration (EDIT THESE VALUES)
SEARCH_TERM = "CLAUDIA ZAPATER" 
MAX_PAGES_TO_SCAN = 15 # Set this higher if needed, e.g., 50. 10 items per page.

# 2. Run the scraper
print("=" * 60)
print(f"Starting Scraper for: '{SEARCH_TERM}' (up to {MAX_PAGES_TO_SCAN} pages)")
print("=" * 60)

df_results = scrape_lavoz_main_search_post(
    search_text=SEARCH_TERM, 
    max_page=MAX_PAGES_TO_SCAN
) 

# 3. Generate Summary & Plot
if not df_results.empty:
    monthly_summary_df = summarize_by_month(df_results)
    fig = create_monthly_plot(monthly_summary_df, SEARCH_TERM)
    
    # 4. Generate Final Files (CSV and PDF)
    csv_file, pdf_file = generate_output_files(df_results, monthly_summary_df, fig, SEARCH_TERM)
    
    print("\n--- Summary Report ---")
    print(f"Total Unique Articles Found: {len(df_results)}")
    print("\nMonthly Article Counts:")
    print(monthly_summary_df)
    
else:
    print("\n🛑 No articles were found for the specified search term.")
