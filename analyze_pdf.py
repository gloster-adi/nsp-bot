import PyPDF2
import re

def analyze_pdf_structure(pdf_path):
    """Analyze PDF structure to understand data format"""
    print(f"\n📊 Analyzing: {pdf_path}\n")
    
    try:
        with open(pdf_path, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            
            # Check first 3 pages
            for page_num in range(min(3, len(reader.pages))):
                page = reader.pages[page_num]
                text = page.extract_text()
                
                print(f"{'='*70}")
                print(f"PAGE {page_num + 1}")
                print(f"{'='*70}")
                print(text[:1500])  # First 1500 chars
                print(f"\n{'='*70}\n")
                
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    pdf_folder = r"c:\Users\Aditya\Downloads\NSP_data"
    import os
    
    for pdf_file in os.listdir(pdf_folder):
        if pdf_file.endswith('.pdf'):
            pdf_path = os.path.join(pdf_folder, pdf_file)
            analyze_pdf_structure(pdf_path)