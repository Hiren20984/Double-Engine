# Weekly Breakout - ALL NSE + ALL BSE - PDF ONLY with TradingView Links - TRUE ATH FIX v2
# FIX: auto_adjust=False (real price like TradingView) + period=max (full history)
import yfinance as yf, pandas as pd, numpy as np, urllib.request, io, os, requests, json, time, zipfile
from datetime import datetime, timedelta
from fpdf import FPDF

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

def send_telegram_pdf(pdf_path, caption):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Secrets empty, PDF not sent"); return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument"
        with open(pdf_path, 'rb') as f:
            r = requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption}, files={"document": f}, timeout=60)
        print(f"Telegram PDF status: {r.status_code} | {r.text[:500]}")
    except Exception as e:
        print(f"Telegram PDF failed: {e}")

def fetch_nse():
    try:
        req = urllib.request.Request("https://archives.nseindia.com/content/equities/EQUITY_L.csv", headers={'User-Agent':'Mozilla/5.0', 'Accept':'text/csv'})
        data = urllib.request.urlopen(req, timeout=30).read().decode('utf-8', errors='ignore')
        df = pd.read_csv(io.StringIO(data))
        col = None
        for c in df.columns:
            if c.strip().upper() == "SYMBOL":
                col = c; break
        syms = df[col].dropna().astype(str).str.strip().tolist()
        syms = [s for s in syms if s and s != "SYMBOL"]
        print(f"Fetched NSE: {len(syms)}")
        return syms
    except Exception as e:
        print(f"NSE fetch failed: {e}")
        return []

def fetch_bse_bhavcopy():
    for days_back in range(1, 8):
        d = datetime.now() - timedelta(days=days_back)
        date_str = d.strftime("%d%m%y")
        url = f"https://www.bseindia.com/download/BhavCopy/Equity/EQ{date_str}_CSV.ZIP"
        print(f"Trying BSE Bhavcopy: {url}")
        try:
            req = urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0', 'Referer':'https://www.bseindia.com/'})
            zip_bytes = urllib.request.urlopen(req, timeout=30).read()
            print(f"Bhavcopy downloaded: {len(zip_bytes)} bytes for {date_str}")
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
                names = z.namelist()
                csv_name = names[0]
                csv_data = z.read(csv_name).decode('utf-8', errors='ignore')
                df = pd.read_csv(io.StringIO(csv_data))
                code_col = None
                for c in df.columns:
                    if c.strip().upper() in ["SC_CODE", "SCCODE", "SCRIP_CODE", "CODE"]:
                        code_col = c; break
                if code_col is None:
                    code_col = df.columns[0]
                codes = df[code_col].dropna().astype(str).str.strip().tolist()
                codes = [c for c in codes if c.isdigit() and len(c)==6]
                codes = list(dict.fromkeys(codes))
                print(f"Fetched BSE via Bhavcopy ({date_str}): {len(codes)} scrips")
                if len(codes) > 1000:
                    return codes
        except Exception as e:
            print(f"Bhavcopy {date_str} failed: {e}")
            continue
    print("All Bhavcopy attempts failed - Trying BSE API fallback")
    try:
        headers = {'User-Agent':'Mozilla/5.0', 'Accept':'application/json', 'Referer':'https://www.bseindia.com/'}
        req = urllib.request.Request("https://api.bseindia.com/BseIndiaAPI/api/ListofScripData/w?segment=Equity&status=Active", headers=headers)
        data = urllib.request.urlopen(req, timeout=30).read().decode('utf-8', errors='ignore')
        j = json.loads(data)
        rows = j.get("Table", []) if isinstance(j, dict) else j
        syms = []
        for r in rows:
            code = r.get("Scrip_Cd") or r.get("scrip_cd")
            if code: syms.append(str(code).strip())
        if len(syms) > 500:
            print(f"Fetched BSE via API: {len(syms)}")
            return syms
    except Exception as e:
        print(f"BSE API also failed: {e}")
    return []

def process_exchange(symbols, suffix, exchange_name):
    tickers = [f"{s}{suffix}" for s in symbols]
    vol_lifetime = []; vol_52w = []; all_lifetime = []; all_52w = []; near_high = []
    CHUNK = 250
    for ci in range(0, len(tickers), CHUNK):
        chunk_tickers = tickers[ci:ci+CHUNK]
        print(f"{exchange_name} Chunk {ci//CHUNK+1}/{(len(tickers)+CHUNK-1)//CHUNK} - {len(chunk_tickers)}")
        try:
            # FIXED: period=max + auto_adjust=False = Real TradingView Price
            data = yf.download(chunk_tickers, period="max", interval="1d", progress=False, auto_adjust=False, threads=False, group_by='ticker')
        except Exception as e:
            print(f"Chunk failed: {e}"); time.sleep(5); continue
        time.sleep(2)
        for ticker in chunk_tickers:
            try:
                sym = ticker.replace(suffix, "")
                dfd = data[ticker].copy() if len(chunk_tickers)>1 else data.copy()
                if dfd is None or len(dfd) < 5: continue
                dfd = dfd.dropna()
                if len(dfd) < 5: continue
                # Use Close column (unadjusted Close, not Adj Close)
                dfw = pd.DataFrame()
                dfw['Close'] = dfd['Close'].resample('W-FRI').last()
                dfw['High'] = dfd['High'].resample('W-FRI').max()
                dfw['Volume'] = dfd['Volume'].resample('W-FRI').sum()
                if len(dfw) < 3: continue
                today_weekday = datetime.now().weekday()
                dfw_closed = dfw.copy()
                if today_weekday < 4:
                    dfw_closed = dfw.iloc[:-1]
                if len(dfw_closed) < 3: continue
                if len(dfw_closed) >= 21:
                    vol_sma21 = float(dfw_closed['Volume'].rolling(21).mean().iloc[-1])
                else:
                    vol_sma21 = float(dfw_closed['Volume'].mean())
                last_vol = float(dfw_closed.iloc[-1]['Volume'])
                if vol_sma21 == 0 or pd.isna(vol_sma21): continue
                vol_ratio = last_vol / vol_sma21
                last_close = float(dfw_closed.iloc[-1]['Close'])
                if len(dfw_closed) > 53:
                    prev_52w_high = float(dfw_closed['High'].iloc[-53:-1].max())
                else:
                    prev_52w_high = float(dfw_closed['High'].iloc[:-1].max()) if len(dfw_closed) > 1 else float(dfw_closed['High'].iloc[-1])
                # TRUE Lifetime High = Max High of ALL history BEFORE last week, unadjusted
                lifetime_high = float(dfw_closed['High'].iloc[:-1].max()) if len(dfw_closed) > 1 else float(dfw_closed['High'].iloc[-1])
                pct_above_52w = (last_close / prev_52w_high - 1) * 100 if prev_52w_high else 0
                pct_above_lifetime = (last_close / lifetime_high - 1) * 100 if lifetime_high else 0
                is_breakout = False; is_lifetime = False
                if last_close > prev_52w_high:
                    is_breakout = True
                    if last_close > lifetime_high:
                        is_lifetime = True
                if is_breakout:
                    if is_lifetime:
                        all_lifetime.append((sym, last_close, lifetime_high, pct_above_lifetime, vol_ratio))
                    else:
                        all_52w.append((sym, last_close, prev_52w_high, pct_above_52w, vol_ratio))
                    if vol_ratio >= 2.0:
                        if is_lifetime:
                            vol_lifetime.append((sym, last_close, lifetime_high, pct_above_lifetime, vol_ratio))
                        else:
                            vol_52w.append((sym, last_close, prev_52w_high, pct_above_52w, vol_ratio))
                elif pct_above_52w > -2.0:
                    near_high.append((sym, last_close, prev_52w_high, pct_above_52w, vol_ratio))
            except: continue
    vol_lifetime = sorted(vol_lifetime, key=lambda x: x[4], reverse=True)
    vol_52w = sorted(vol_52w, key=lambda x: x[4], reverse=True)
    all_lifetime = sorted(all_lifetime, key=lambda x: x[4], reverse=True)
    all_52w = sorted(all_52w, key=lambda x: x[4], reverse=True)
    near_high = sorted(near_high, key=lambda x: x[3], reverse=True)
    print(f"{exchange_name} - Vol Lifetime: {len(vol_lifetime)} | Vol 52W: {len(vol_52w)} | ALL Lifetime: {len(all_lifetime)} | ALL 52W: {len(all_52w)} | Near: {len(near_high)}")
    return vol_lifetime, vol_52w, all_lifetime, all_52w, near_high

def generate_pdf(today, nse_data, bse_data, nse_total, bse_total):
    pdf = FPDF(orientation='P', unit='mm', format='A4')
    pdf.set_auto_page_break(auto=True, margin=15)
    def clean(s):
        return s.encode('latin-1', 'replace').decode('latin-1')
    def tv_link(exchange, sym):
        return f"https://www.tradingview.com/chart/?symbol={exchange}:{sym}"
    def add_title(title, subtitle):
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 18)
        pdf.cell(0, 12, clean(title), new_x="LMARGIN", new_y="NEXT", align="C")
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(0, 7, clean(subtitle), new_x="LMARGIN", new_y="NEXT", align="C")
        pdf.set_font("Helvetica", "I", 9)
        pdf.set_text_color(0, 0, 255)
        pdf.cell(0, 6, "Click on Symbol (blue) to open TradingView Chart", new_x="LMARGIN", new_y="NEXT", align="C")
        pdf.set_text_color(0, 0, 0)
        pdf.ln(3)
    def add_table(heading, rows, pct_label, exchange):
        if not rows:
            pdf.set_font("Helvetica", "B", 12)
            pdf.cell(0, 8, clean(heading), new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", "", 10)
            pdf.cell(0, 7, "None this week", new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)
            return
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, clean(f"{heading} ({len(rows)})"), new_x="LMARGIN", new_y="NEXT")
        pdf.set_fill_color(30, 30, 30)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("Helvetica", "B", 8)
        pdf.cell(10, 7, "#", border=1, fill=True)
        pdf.cell(42, 7, "Symbol", border=1, fill=True)
        pdf.cell(28, 7, "Price", border=1, fill=True)
        pdf.cell(32, 7, "Prev High", border=1, fill=True)
        pdf.cell(32, 7, pct_label, border=1, fill=True)
        pdf.cell(36, 7, "Vol", border=1, fill=True, new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)
        for i, (sym, close, high, pct, vr) in enumerate(rows, 1):
            if i % 2 == 0:
                pdf.set_fill_color(240, 240, 240)
            else:
                pdf.set_fill_color(255, 255, 255)
            pdf.set_font("Helvetica", "", 8)
            pdf.cell(10, 6, str(i), border=1, fill=True)
            pdf.set_text_color(0, 0, 255)
            pdf.set_font("Helvetica", "U", 8)
            pdf.cell(42, 6, clean(str(sym)), border=1, fill=True, link=tv_link(exchange, str(sym)))
            pdf.set_text_color(0, 0, 0)
            pdf.set_font("Helvetica", "", 8)
            pdf.cell(28, 6, f"{close:.2f}", border=1, fill=True)
            pdf.cell(32, 6, f"{high:.2f}", border=1, fill=True)
            pdf.cell(32, 6, f"+{pct:.1f}%", border=1, fill=True)
            pdf.cell(36, 6, f"{vr:.1f}x", border=1, fill=True, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)
    def add_near_table(heading, rows, exchange):
        if not rows:
            return
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, clean(f"{heading} ({len(rows)})"), new_x="LMARGIN", new_y="NEXT")
        pdf.set_fill_color(30, 30, 30); pdf.set_text_color(255, 255, 255); pdf.set_font("Helvetica", "B", 8)
        pdf.cell(10, 7, "#", border=1, fill=True); pdf.cell(42, 7, "Symbol", border=1, fill=True); pdf.cell(28, 7, "Price", border=1, fill=True); pdf.cell(32, 7, "Prev 52W High", border=1, fill=True); pdf.cell(32, 7, "Below 52W", border=1, fill=True); pdf.cell(36, 7, "Vol", border=1, fill=True, new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)
        for i, (sym, close, high, pct, vr) in enumerate(rows, 1):
            if i % 2 == 0:
                pdf.set_fill_color(240, 240, 240)
            else:
                pdf.set_fill_color(255, 255, 255)
            pdf.set_font("Helvetica", "", 8)
            pdf.cell(10, 6, str(i), border=1, fill=True)
            pdf.set_text_color(0, 0, 255)
            pdf.set_font("Helvetica", "U", 8)
            pdf.cell(42, 6, clean(str(sym)), border=1, fill=True, link=tv_link(exchange, str(sym)))
            pdf.set_text_color(0, 0, 0)
            pdf.set_font("Helvetica", "", 8)
            pdf.cell(28, 6, f"{close:.2f}", border=1, fill=True); pdf.cell(32, 6, f"{high:.2f}", border=1, fill=True); pdf.cell(32, 6, f"{pct:.1f}%", border=1, fill=True); pdf.cell(36, 6, f"{vr:.1f}x", border=1, fill=True, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)
    pdf.add_page()
    pdf.ln(40)
    pdf.set_font("Helvetica", "B", 26)
    pdf.cell(0, 15, "WEEKLY BREAKOUT", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.set_font("Helvetica", "", 14)
    pdf.cell(0, 10, clean(f"NSE + BSE | {today}"), new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(5)
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 7, clean(f"NSE Universe: {nse_total} | BSE Universe: {bse_total}"), new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.cell(0, 7, "Filter: Weekly Vol > 2x SMA 21 | No 260 Days Filter", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.cell(0, 7, "Price = Unadjusted (Like TradingView) | ATH = True ATH Since IPO", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.set_font("Helvetica", "I", 10)
    pdf.set_text_color(0, 0, 255)
    pdf.cell(0, 7, "Click any Symbol in PDF to open TradingView Chart", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.set_text_color(0, 0, 0)
    pdf.ln(10)
    vlt_n, v52_n, alt_n, a52_n, near_n = nse_data
    vlt_b, v52_b, alt_b, a52_b, near_b = bse_data
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "SUMMARY", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 7, clean(f"NSE - Vol Lifetime: {len(vlt_n)} | Vol 52W: {len(v52_n)} | ALL Lifetime: {len(alt_n)} | ALL 52W: {len(a52_n)} | Near: {len(near_n)}"), new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.cell(0, 7, clean(f"BSE - Vol Lifetime: {len(vlt_b)} | Vol 52W: {len(v52_b)} | ALL Lifetime: {len(alt_b)} | ALL 52W: {len(a52_b)} | Near: {len(near_b)}"), new_x="LMARGIN", new_y="NEXT", align="C")
    add_title("NSE - LIST 1: Vol 2x", f"Weekly Vol > 2x SMA 21 | {today}")
    add_table("LIFETIME HIGH + Vol 2x - TRUE ATH", vlt_n, "Above ATH", "NSE")
    add_table("52W HIGH + Vol 2x", v52_n, "Above 52W", "NSE")
    add_title("NSE - LIST 2: ALL Breakouts", f"No Volume Filter | {today}")
    add_table("ALL LIFETIME HIGH - TRUE ATH", alt_n, "Above ATH", "NSE")
    add_table("ALL 52W HIGH", a52_n, "Above 52W", "NSE")
    add_near_table("NEAR HIGH - Watch Next Week", near_n, "NSE")
    add_title("BSE - LIST 1: Vol 2x", f"Weekly Vol > 2x SMA 21 | {today}")
    add_table("LIFETIME HIGH + Vol 2x - TRUE ATH", vlt_b, "Above ATH", "BSE")
    add_table("52W HIGH + Vol 2x", v52_b, "Above 52W", "BSE")
    add_title("BSE - LIST 2: ALL Breakouts", f"No Volume Filter | {today}")
    add_table("ALL LIFETIME HIGH - TRUE ATH", alt_b, "Above ATH", "BSE")
    add_table("ALL 52W HIGH", a52_b, "Above 52W", "BSE")
    add_near_table("NEAR HIGH - Watch Next Week", near_b, "BSE")
    pdf_path = f"Weekly_Breakout_{today}.pdf"
    pdf.output(pdf_path)
    print(f"PDF generated: {pdf_path}")
    return pdf_path

def main():
    today = datetime.now().strftime('%Y-%m-%d')
    print(f"=== Weekly Breakout NSE+BSE - PDF ONLY TRUE ATH v2 - {today} ===")
    nse_syms = fetch_nse()
    nse_syms = list(dict.fromkeys(nse_syms))
    vol_lt_nse, vol_52_nse, all_lt_nse, all_52_nse, near_nse = process_exchange(nse_syms, ".NS", "NSE")
    nse_data = (vol_lt_nse, vol_52_nse, all_lt_nse, all_52_nse, near_nse)
    bse_syms = fetch_bse_bhavcopy()
    bse_syms = list(dict.fromkeys(bse_syms))
    if len(bse_syms) > 500:
        vol_lt_bse, vol_52_bse, all_lt_bse, all_52_bse, near_bse = process_exchange(bse_syms, ".BO", "BSE")
        bse_data = (vol_lt_bse, vol_52_bse, all_lt_bse, all_52_bse, near_bse)
    else:
        print("BSE skipped - Bhavcopy + API both failed, NSE PDF will still send")
        bse_data = ([], [], [], [], [])
    try:
        pdf_path = generate_pdf(today, nse_data, bse_data, len(nse_syms), len(bse_syms))
        send_telegram_pdf(pdf_path, f"📄 WEEKLY BREAKOUT - NSE + BSE | {today}\nTRUE ATH Fixed (Unadjusted Price) - Click Symbol for TradingView")
    except Exception as e:
        print(f"PDF failed: {e}")

if __name__ == "__main__":
    main()