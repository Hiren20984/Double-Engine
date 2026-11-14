# Weekly Breakout - ALL NSE + ALL BSE - 4 Messages - No 260 Days Filter
import yfinance as yf, pandas as pd, numpy as np, urllib.request, io, os, requests, json
from datetime import datetime

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

def send_telegram(msg):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print(msg); return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        for i in range(0, len(msg), 4000):
            requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg[i:i+4000], "parse_mode": "Markdown"}, timeout=15)
    except Exception as e:
        print(f"Telegram failed: {e}")

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

def fetch_bse():
    # Try BSE API - Active Equity Scrips
    try:
        req = urllib.request.Request("https://api.bseindia.com/BseIndiaAPI/api/ListofScripData/w?segment=Equity&status=Active", headers={'User-Agent':'Mozilla/5.0', 'Referer':'https://www.bseindia.com/'})
        data = urllib.request.urlopen(req, timeout=30).read().decode('utf-8', errors='ignore')
        j = json.loads(data)
        # BSE API returns list with Scrip_Cd and Scrip_Name / Symbol
        syms = []
        # It returns Table array
        rows = j.get("Table", []) if isinstance(j, dict) else j
        for r in rows:
            # Scrip code is numeric, yfinance BSE uses Scrip_Cd.BO e.g. 500325.BO
            code = r.get("Scrip_Cd") or r.get("scrip_cd") or r.get("ScripCode")
            if code:
                syms.append(str(code).strip())
        if len(syms) > 500:
            print(f"Fetched BSE via API: {len(syms)}")
            return syms
        print(f"BSE API returned only {len(syms)}, trying fallback")
    except Exception as e:
        print(f"BSE API failed: {e}")
    # Fallback: Use NSE symbols with .BO suffix - Most large/mid caps are listed on both
    # This ensures BSE list still works even if BSE API blocks
    nse = fetch_nse()
    print(f"BSE Fallback: Using NSE symbols as BSE symbols: {len(nse)}")
    return nse

def process_exchange(symbols, suffix, exchange_name):
    # suffix: .NS for NSE, .BO for BSE
    # NO 260 DAYS FILTER - Only need minimum 5 weekly bars
    tickers = [f"{s}{suffix}" for s in symbols]
    vol_lifetime = []
    vol_52w = []
    all_lifetime = []
    all_52w = []
    near_high = []

    CHUNK = 500
    for ci in range(0, len(tickers), CHUNK):
        chunk_tickers = tickers[ci:ci+CHUNK]
        print(f"{exchange_name} Chunk {ci//CHUNK+1}/{(len(tickers)+CHUNK-1)//CHUNK} - {len(chunk_tickers)}")
        try:
            data = yf.download(chunk_tickers, period="3y", interval="1d", progress=False, auto_adjust=True, threads=True, group_by='ticker')
        except Exception as e:
            print(f"Chunk failed: {e}"); continue

        for ticker in chunk_tickers:
            try:
                sym = ticker.replace(suffix, "")
                dfd = data[ticker].copy() if len(chunk_tickers)>1 else data.copy()
                if dfd is None or len(dfd) < 5: continue
                dfd = dfd.dropna()
                if len(dfd) < 5: continue

                dfw = pd.DataFrame()
                dfw['Close'] = dfd['Close'].resample('W-FRI').last()
                dfw['High'] = dfd['High'].resample('W-FRI').max()
                dfw['Volume'] = dfd['Volume'].resample('W-FRI').sum()
                if len(dfw) < 3: continue

                # Volume: Weekly Vol vs Weekly SMA 21 - If less than 21 weeks, use average of available weeks
                if len(dfw) >= 21:
                    vol_sma21 = float(dfw['Volume'].rolling(21).mean().iloc[-1])
                else:
                    vol_sma21 = float(dfw['Volume'].mean())
                last_vol = float(dfw.iloc[-1]['Volume'])
                if vol_sma21 == 0 or pd.isna(vol_sma21): continue
                vol_ratio = last_vol / vol_sma21

                last_close = float(dfw.iloc[-1]['Close'])
                # 52W High = Max of last 52 weeks excluding this week, or all available if less than 52 weeks
                if len(dfw) > 53:
                    prev_52w_high = float(dfw['High'].iloc[-53:-1].max())
                else:
                    prev_52w_high = float(dfw['High'].iloc[:-1].max()) if len(dfw) > 1 else float(dfw['High'].iloc[-1])
                lifetime_high = float(dfw['High'].iloc[:-1].max()) if len(dfw) > 1 else float(dfw['High'].iloc[-1])
                pct_above_52w = (last_close / prev_52w_high - 1) * 100 if prev_52w_high else 0
                pct_above_lifetime = (last_close / lifetime_high - 1) * 100 if lifetime_high else 0

                is_breakout = False
                is_lifetime = False
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

def build_msg_list1(exchange, total, vol_lifetime, vol_52w, today):
    msg = f"🚀 *WEEKLY BREAKOUT - {exchange} - LIST 1: Vol 2x* | {today}\n"
    msg += f"Universe: {exchange} {total} | Filter: Weekly Vol > 2x SMA 21 | No 260 Days Filter\n\n"
    if vol_lifetime:
        msg += f"*🏆 LIFETIME HIGH + Vol 2x ({len(vol_lifetime)}):*\n"
        for sym, close, high, pct, vr in vol_lifetime[:30]:
            msg += f"• {sym} @ {close:.2f} | +{pct:.1f}% ATH | Vol {vr:.1f}x\n"
        if len(vol_lifetime) > 30: msg += f"+ {len(vol_lifetime)-30} more...\n"
        msg += "\n"
    else:
        msg += "*🏆 LIFETIME HIGH + Vol 2x:* None this week\n\n"
    if vol_52w:
        msg += f"*📈 52W HIGH + Vol 2x ({len(vol_52w)}):*\n"
        for sym, close, high, pct, vr in vol_52w[:30]:
            msg += f"• {sym} @ {close:.2f} | +{pct:.1f}% 52W | Vol {vr:.1f}x\n"
        if len(vol_52w) > 30: msg += f"+ {len(vol_52w)-30} more...\n"
        msg += "\n"
    else:
        msg += "*📈 52W HIGH + Vol 2x:* None this week\n\n"
    return msg

def build_msg_list2(exchange, total, all_lifetime, all_52w, near_high, today):
    msg = f"📋 *WEEKLY BREAKOUT - {exchange} - LIST 2: ALL Breakouts* | {today}\n"
    msg += f"Universe: {exchange} {total} | No Volume Filter | No 260 Days Filter\n\n"
    if all_lifetime:
        msg += f"*🏆 ALL LIFETIME HIGH ({len(all_lifetime)}):*\n"
        for sym, close, high, pct, vr in all_lifetime[:40]:
            msg += f"• {sym} @ {close:.2f} | +{pct:.1f}% ATH | Vol {vr:.1f}x\n"
        if len(all_lifetime) > 40: msg += f"+ {len(all_lifetime)-40} more...\n"
        msg += "\n"
    else:
        msg += "*🏆 ALL LIFETIME HIGH:* None this week\n\n"
    if all_52w:
        msg += f"*📈 ALL 52W HIGH ({len(all_52w)}):*\n"
        for sym, close, high, pct, vr in all_52w[:40]:
            msg += f"• {sym} @ {close:.2f} | +{pct:.1f}% 52W | Vol {vr:.1f}x\n"
        if len(all_52w) > 40: msg += f"+ {len(all_52w)-40} more...\n"
        msg += "\n"
    else:
        msg += "*📈 ALL 52W HIGH:* None this week\n\n"
    if near_high:
        msg += f"*👀 NEAR HIGH - Watch Next Week ({len(near_high)}):*\n"
        for sym, close, high, pct, vr in near_high[:20]:
            msg += f"• {sym} @ {close:.2f} | {pct:.1f}% below 52W | Vol {vr:.1f}x\n"
        if len(near_high) > 20: msg += f"+ {len(near_high)-20} more...\n"
    return msg

def main():
    today = datetime.now().strftime('%Y-%m-%d')
    print(f"=== Weekly Breakout NSE+BSE - 4 Messages - {today} ===")

    # NSE
    nse_syms = fetch_nse()
    nse_syms = list(dict.fromkeys(nse_syms))
    vol_lt_nse, vol_52_nse, all_lt_nse, all_52_nse, near_nse = process_exchange(nse_syms, ".NS", "NSE")
    msg1_nse = build_msg_list1("NSE", len(nse_syms), vol_lt_nse, vol_52_nse, today)
    msg2_nse = build_msg_list2("NSE", len(nse_syms), all_lt_nse, all_52_nse, near_nse, today)
    print("=== NSE MSG1 ==="); print(msg1_nse)
    print("=== NSE MSG2 ==="); print(msg2_nse)
    send_telegram(msg1_nse)
    send_telegram(msg2_nse)

    # BSE
    bse_syms = fetch_bse()
    bse_syms = list(dict.fromkeys(bse_syms))
    vol_lt_bse, vol_52_bse, all_lt_bse, all_52_bse, near_bse = process_exchange(bse_syms, ".BO", "BSE")
    msg1_bse = build_msg_list1("BSE", len(bse_syms), vol_lt_bse, vol_52_bse, today)
    msg2_bse = build_msg_list2("BSE", len(bse_syms), all_lt_bse, all_52_bse, near_bse, today)
    print("=== BSE MSG1 ==="); print(msg1_bse)
    print("=== BSE MSG2 ==="); print(msg2_bse)
    send_telegram(msg1_bse)
    send_telegram(msg2_bse)

if __name__ == "__main__":
    main()
