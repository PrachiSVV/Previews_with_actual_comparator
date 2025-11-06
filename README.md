# 📊 Results vs Expectations Dashboard
A Streamlit-based analytics dashboard to compare **Actual** vs **Broker Expected** results for Sales, EBITDA, PAT, and margins — along with beat/inline/miss analysis.

This app includes:
✅ Secure login  
✅ Auto-loading CSV from GitHub raw URL  
✅ Calculation of EBITDA margin (actual & expected)  
✅ Summary table (Expected vs Actual vs Difference vs Beat Flags)  
✅ Interactive charts for brokers  
✅ Filter panel (brokers, flags, picked type, etc.)  
✅ CSV export  

---

## 🚀 Features

### ✅ Secure Login
Uses SHA256 hashed passwords stored in `secrets.toml`.

### ✅ Data Processing
- Auto-validates CSV schema  
- Converts numeric columns  
- Loads data from GitHub raw CSV URL  
- Computes:
  - Actual EBITDA Margin = `ebitda / sales * 100`
  - Expected EBITDA Margin = `expected_ebitda / expected_sales * 100`
  - %-diff and bps comparisons  

### ✅ Visualizations
- Actual vs Expected grouped bar chart  
- Beat percentage chart (Sales/PAT/EBITDA)  

### ✅ Summary Table (Excel-style layout)
Matches the structure:
- Expected  
- Actual  
- Compare (%, bps)  
- Beat Flags  
- Total Beats  

---

## 📁 Folder Structure

