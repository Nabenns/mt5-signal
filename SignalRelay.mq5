//+------------------------------------------------------------------+
//|                                                  SignalRelay.mq5 |
//|               MT5 -> VPS receiver -> Telegram (Wait-Complete)    |
//| Version: V10 - Wait for SL+TP complete, retry 3x, no ghost send  |
//+------------------------------------------------------------------+
// Rules:
// 1. Track position SL/TP changes
// 2. When BOTH SL > 0 AND TP > 0 -> SEND ENTRY with SL & TP complete
// 3. If only one is set, wait up to 10 seconds (grace period)
// 4. After sending, ignore all future adjustments (no second message)
// 5. Lock per symbol: suppress duplicate entries while position active
//
// Format output: "💰 BUY NOW XAUUSD 4820 | SL 4815 | TP 4835"
// OR: "💰 BUY NOW XAUUSD 4820" (if SL/TP still 0)
//+------------------------------------------------------------------+
#property copyright "SignalRelay V10"
#property version   "10.00"
#property description "Wait SL+TP, send entry+SLTP separated"

input string InpReceiverURL    = "https://hirmes.bensserver.cloud/api/signal";   
input string InpReceiverSecret = "3e0371e7c5673317fc134f192e0b7df4dc7a980e8b4fb610"; 
input int    InpTimeoutMs      = 3000;
input long   InpMagicFilter    = 0;
input int    InpTimerSec       = 2;     // Interval cek SL/TP (detik)
input bool   InpNotifyStartup  = true;

#define PROC_RING 128
#define SLTP_GRACE_SECONDS 10  // Grace period jika cuma salah satu yang diset

ulong g_processed[PROC_RING];
int   g_proc_count = 0;

ulong  g_tickets[];
double g_sl_snap[];
double g_tp_snap[];
bool   g_sent[];
long   g_set_time[];      // Kapan posisi pertama kali diset SL/TP
int    g_tracked = 0;

string JsonEscape(string s)
  {
   StringReplace(s, "\\", "\\\\");
   StringReplace(s, "\"", "\\\"");
   StringReplace(s, "\n", "\\n");
   StringReplace(s, "\r", "");
   return s;
  }

bool SendPayload(const string json)
  {
   if(MQLInfoInteger(MQL_TESTER)) return true;

   string headers = "Content-Type: application/json\r\nX-Signal-Secret: " + InpReceiverSecret + "\r\n";
   char data[];
   int len = StringLen(json);
   if(len > 0) StringToCharArray(json, data, 0, len, CP_UTF8); else ArrayResize(data, 0);

   for(int attempt = 1; attempt <= 3; attempt++)
     {
      char result[];
      string result_headers;
      int code = WebRequest("POST", InpReceiverURL, headers, InpTimeoutMs, data, result, result_headers);
      if(code > 0)
        {
         Print("[SignalRelay] OK, HTTP ", code);
         return (code >= 200 && code < 300);
        }
      int err = GetLastError();
      Print("[SignalRelay] WebRequest GAGAL attempt ", attempt, " error ", err,
            (err == 4014 ? " (URL belum di-whitelist!)" : ""));
      if(attempt < 3) Sleep(700);
     }
   return false;
  }

string BuildJSON(string action, string symbol, string side, double lot,
                 double price, double sl, double tp, long magic,
                 ulong deal, ulong position, int digits)
  {
   string json = "{";
   json += "\"action\":\"" + JsonEscape(action) + "\",";
   json += "\"symbol\":\"" + JsonEscape(symbol) + "\",";
   json += "\"type\":\"" + JsonEscape(side) + "\",";
   json += "\"lot\":" + DoubleToString(lot, 2) + ",";
   json += "\"price\":" + DoubleToString(price, digits) + ",";
   json += "\"sl\":" + DoubleToString(sl, digits) + ",";
   json += "\"tp\":" + DoubleToString(tp, digits) + ",";
   json += "\"magic\":" + IntegerToString(magic) + ",";
   json += "\"comment\":\"\",";
   json += "\"deal\":" + IntegerToString((long)deal) + ",";
   json += "\"position\":" + IntegerToString((long)position) + ",";
   json += "\"digits\":" + IntegerToString(digits);
   json += "}";
   return json;
  }

bool IsProcessed(ulong ticket)
  {
   for(int i = 0; i < PROC_RING; i++)
      if(g_processed[i] == ticket)
         return true;
   return false;
  }

void MarkProcessed(ulong ticket)
  {
   g_processed[g_proc_count % PROC_RING] = ticket;
   g_proc_count++;
  }

void AddTracked(ulong ticket, double sl, double tp, bool sent)
  {
   ArrayResize(g_tickets, g_tracked + 1);
   ArrayResize(g_sl_snap, g_tracked + 1);
   ArrayResize(g_tp_snap, g_tracked + 1);
   ArrayResize(g_sent, g_tracked + 1);
   ArrayResize(g_set_time, g_tracked + 1);
   g_tickets[g_tracked]   = ticket;
   g_sl_snap[g_tracked]   = sl;
   g_tp_snap[g_tracked]   = tp;
   g_sent[g_tracked]      = sent;
   g_set_time[g_tracked]  = 0;
   g_tracked++;
  }

void RemoveTracked(int idx)
  {
   for(int i = idx; i < g_tracked - 1; i++)
     {
      g_tickets[i]   = g_tickets[i + 1];
      g_sl_snap[i]   = g_sl_snap[i + 1];
      g_tp_snap[i]   = g_tp_snap[i + 1];
      g_sent[i]      = g_sent[i + 1];
      g_set_time[i]  = g_set_time[i + 1];
     }
   g_tracked--;
   ArrayResize(g_tickets, g_tracked);
   ArrayResize(g_sl_snap, g_tracked);
   ArrayResize(g_tp_snap, g_tracked);
   ArrayResize(g_sent, g_tracked);
   ArrayResize(g_set_time, g_tracked);
  }

//+------------------------------------------------------------------+
int OnInit()
  {
   ArrayInitialize(g_processed, 0);
   ArrayResize(g_tickets, 0);
   ArrayResize(g_sl_snap, 0);
   ArrayResize(g_tp_snap, 0);
   ArrayResize(g_sent, 0);
   ArrayResize(g_set_time, 0);
   g_tracked = 0;

   HistorySelect(0, TimeCurrent());
   EventSetTimer(InpTimerSec);

   Print("[SignalRelay V10] ready -- receiver: ", InpReceiverURL,
         " | magic filter: ", (InpMagicFilter == 0 ? "SEMUA" : IntegerToString(InpMagicFilter)));

   if(InpNotifyStartup && !MQLInfoInteger(MQL_TESTER))
     {
      string msg = "SignalRelay V10 ONLINE - Akun "
                   + IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN));
      SendPayload("{\"action\":\"NOTICE\",\"comment\":\"" + JsonEscape(msg) + "\",\"deal\":0}");
     }
   return(INIT_SUCCEEDED);
  }

void OnDeinit(const int reason)
  {
   EventKillTimer();
  }

//+------------------------------------------------------------------+
void OnTradeTransaction(const MqlTradeTransaction& trans,
                        const MqlTradeRequest& request,
                        const MqlTradeResult& result)
  {
   ulong ticket = trans.deal;
   if(ticket == 0 || IsProcessed(ticket) || !HistoryDealSelect(ticket)) return;

   long deal_type = HistoryDealGetInteger(ticket, DEAL_TYPE);
   if(deal_type != DEAL_TYPE_BUY && deal_type != DEAL_TYPE_SELL) return;

   long entry = HistoryDealGetInteger(ticket, DEAL_ENTRY);
   string symbol = HistoryDealGetString(ticket, DEAL_SYMBOL);
   if(symbol == "") symbol = trans.symbol;
   int digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
   if(digits <= 0) digits = 5;

   long magic = HistoryDealGetInteger(ticket, DEAL_MAGIC);
   if(InpMagicFilter > 0 && magic != InpMagicFilter) return;

   MarkProcessed(trans.deal);

   if(entry == DEAL_ENTRY_IN || entry == DEAL_ENTRY_INOUT)
     {
      string side = (deal_type == DEAL_TYPE_BUY) ? "BUY" : "SELL";
      double volume = HistoryDealGetDouble(trans.deal, DEAL_VOLUME);
      double price  = HistoryDealGetDouble(trans.deal, DEAL_PRICE);
      ulong  pos_id = trans.position;
      if(pos_id == 0) pos_id = (ulong)HistoryDealGetInteger(trans.deal, DEAL_POSITION_ID);

      // Check current SL/TP
      double sl = 0.0, tp = 0.0;
      if(pos_id > 0 && PositionSelectByTicket(pos_id))
        {
         sl = PositionGetDouble(POSITION_SL);
         tp = PositionGetDouble(POSITION_TP);
        }

      AddTracked(pos_id, sl, tp, false);
      Print("[SignalRelay] OPEN tracked ", side, " ", symbol, " pos ", pos_id);
     }
     
   if(entry == DEAL_ENTRY_OUT || entry == DEAL_ENTRY_OUT_BY)
     {
      string side = (deal_type == DEAL_TYPE_BUY) ? "SELL" : "BUY";
      double volume = HistoryDealGetDouble(trans.deal, DEAL_VOLUME);
      double price  = HistoryDealGetDouble(trans.deal, DEAL_PRICE);
      ulong  pos_id = trans.position;
      if(pos_id == 0) pos_id = (ulong)HistoryDealGetInteger(trans.deal, DEAL_POSITION_ID);

      SendPayload(BuildJSON("CLOSE", symbol, side, volume, price, 0.0, 0.0,
                            magic, trans.deal, pos_id, digits));
      Print("[SignalRelay] CLOSE ", symbol, " pos ", pos_id);
     }
  }

//+------------------------------------------------------------------+
void OnTimer()
  {
   int total = PositionsTotal();

   // Cleanup closed positions
   for(int i = g_tracked - 1; i >= 0; i--)
     {
      bool found = false;
      for(int j = 0; j < total; j++)
        {
         if(PositionGetTicket(j) == g_tickets[i])
           {
            found = true;
            break;
           }
        }
      if(!found) RemoveTracked(i);
     }

   // Check SL/TP updates on tracked positions
   long now_ts = (long)TimeCurrent();
   for(int i = 0; i < g_tracked; i++)
     {
      if(g_sent[i]) continue; // Sudah terkirim, skip
      if(!PositionSelectByTicket(g_tickets[i])) continue;

      double sl = PositionGetDouble(POSITION_SL);
      double tp = PositionGetDouble(POSITION_TP);

      // Update snapshot kalau berubah
      if(sl != g_sl_snap[i] || tp != g_tp_snap[i])
        {
         g_sl_snap[i] = sl;
         g_tp_snap[i] = tp;
         
         // Start timer kalau salah satu udah diset
         if((sl > 0 || tp > 0) && g_set_time[i] == 0)
            g_set_time[i] = now_ts;
        }

      if(sl <= 0 && tp <= 0)
        {
         g_set_time[i] = 0; // Reset kalau kosong lagi
         continue;
        }

      // Check conditions:
      // 1. Both SL & TP ready? -> Send immediately
      // 2. Only one ready but grace period expired? -> Send anyway
      bool both_ready = (sl > 0 && tp > 0);
      bool grace_expired = (g_set_time[i] > 0 && (now_ts - g_set_time[i]) >= SLTP_GRACE_SECONDS);

      if(!both_ready && !grace_expired)
         continue; // Still waiting

      // Get position details for sending
      string symbol = PositionGetString(POSITION_SYMBOL);
      int digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
      if(digits <= 0) digits = 5;
      long ptype = PositionGetInteger(POSITION_TYPE);
      string side = (ptype == POSITION_TYPE_BUY) ? "BUY" : "SELL";
      double volume = PositionGetDouble(POSITION_VOLUME);
      double price  = PositionGetDouble(POSITION_PRICE_OPEN);
      long magic = PositionGetInteger(POSITION_MAGIC);

      // Send single entry message with SL & TP
      bool ok = SendPayload(BuildJSON("OPEN", symbol, side, volume, price, sl, tp,
                            magic, 0, g_tickets[i], digits));
      
      if(ok)
        {
         g_sent[i] = true;
         Print("[SignalRelay] SENT ENTRY ", symbol, " SL=", DoubleToString(sl, digits), " TP=", DoubleToString(tp, digits));
        }
      else
         Print("[SignalRelay] GAGAL kirim ", symbol, " — retry di tick berikutnya");
     }
  }
//+------------------------------------------------------------------+
