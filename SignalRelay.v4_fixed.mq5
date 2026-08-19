//+------------------------------------------------------------------+
//|                                                  SignalRelay.mq5 |
//|                    MT5 -> Telegram signal relay via VPS receiver |
//+------------------------------------------------------------------+
#property copyright   "SignalRelay v4"
#property version     "4.00"
#property description "Kirim notifikasi Telegram setiap posisi open/close (incl. SL/TP hit)."
#property description "Attach ke SATU chart saja -- event trade bersifat terminal-wide."

//--- inputs ----------------------------------------------------------
input string InpReceiverURL    = "https://hirmes.bensserver.cloud/api/signal";
input string InpReceiverSecret = "3e0371e7c5673317fc134f192e0b7df4dc7a980e8b4fb610"; 
input int    InpTimeoutMs      = 3000;
input long   InpMagicFilter    = 0;
input bool   InpNotifyStartup  = true;

//--- globals ---------------------------------------------------------
#define PROC_RING 128
ulong g_processed[PROC_RING];
int   g_proc_count = 0;

//+------------------------------------------------------------------+
int OnInit()
  {
   ArrayInitialize(g_processed, 0);
   Print("[SignalRelay] ready -- receiver: ", InpReceiverURL,
         " | magic filter: ", (InpMagicFilter == 0 ? "SEMUA" : IntegerToString(InpMagicFilter)));

   if(InpNotifyStartup && !MQLInfoInteger(MQL_TESTER))
     {
      string msg = "\uD83E\uDD16 SignalRelay ONLINE\nAkun: " + IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN)) + "\nServer: " + AccountInfoString(ACCOUNT_SERVER);
      SendPayload(BuildNotice(msg));
     }
   return(INIT_SUCCEEDED);
  }

//+------------------------------------------------------------------+
void OnTradeTransaction(const MqlTradeTransaction& trans, const MqlTradeRequest& request, const MqlTradeResult& result)
  {
   if(trans.type != TRADE_TRANSACTION_DEAL_ADD) return;
   
   ulong ticket = trans.deal;
   if(ticket == 0 || IsProcessed(ticket) || !HistoryDealSelect(ticket)) return;
   
   long deal_type = HistoryDealGetInteger(ticket, DEAL_TYPE);
   if(deal_type != DEAL_TYPE_BUY && deal_type != DEAL_TYPE_SELL) return;
   
   long entry = HistoryDealGetInteger(ticket, DEAL_ENTRY);
   bool is_open = (entry == DEAL_ENTRY_IN);
   bool is_close = (entry == DEAL_ENTRY_OUT || entry == DEAL_ENTRY_OUT_BY || entry == DEAL_ENTRY_INOUT);
   if(!is_open && !is_close) return;
   
   long magic = HistoryDealGetInteger(ticket, DEAL_MAGIC);
   if(InpMagicFilter > 0 && magic != InpMagicFilter) return;
   
   MarkProcessed(ticket);
   SendDealSignal(ticket, is_open, request);
  }

//+------------------------------------------------------------------+
void SendDealSignal(ulong ticket, bool is_open, const MqlTradeRequest& request)
  {
   string symbol  = HistoryDealGetString(ticket, DEAL_SYMBOL);
   long   dtype   = HistoryDealGetInteger(ticket, DEAL_TYPE);
   string side    = (dtype == DEAL_TYPE_BUY) ? "BUY" : "SELL";
   double volume  = HistoryDealGetDouble(ticket, DEAL_VOLUME);
   double price   = HistoryDealGetDouble(ticket, DEAL_PRICE);
   double profit  = HistoryDealGetDouble(ticket, DEAL_PROFIT) + HistoryDealGetDouble(ticket, DEAL_SWAP) + HistoryDealGetDouble(ticket, DEAL_COMMISSION);
   long   magic   = HistoryDealGetInteger(ticket, DEAL_MAGIC);
   string comment = HistoryDealGetString(ticket, DEAL_COMMENT);
   ulong  pos_id  = (ulong)HistoryDealGetInteger(ticket, DEAL_POSITION_ID);
   
   int digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
   if(digits <= 0) digits = 5;
   
   // SL/TP: loop positions first, fallback to request
   double sl = 0.0, tp = 0.0;
   bool found = false;
   if(pos_id > 0)
     {
      for(int i = PositionsTotal() - 1; i >= 0; i--)
        {
         ulong ptk = PositionGetTicket(i);
         if(ptk == pos_id)
           {
            sl = PositionGetDouble(POSITION_SL);
            tp = PositionGetDouble(POSITION_TP);
            found = true;
            break;
           }
        }
     }
   if(!found && is_open) { sl = request.sl; tp = request.tp; }
   
   string action = is_open ? "OPEN" : "CLOSE";
   string json = StringFormat("{\"action\":\"%s\",\"symbol\":\"%s\",\"type\":\"%s\",\"lot\":%.2f,\"price\":%s,\"sl\":%s,\"tp\":%s,\"profit\":%.2f,\"magic\":%d,\"comment\":\"%s\",\"deal\":%llu,\"position\":%llu,\"digits\":%d}",
      action, JsonEscape(symbol), side, volume, DoubleToString(price, digits), DoubleToString(sl, digits), DoubleToString(tp, digits), is_open ? 0.0 : profit, (int)magic, JsonEscape(comment), ticket, pos_id, digits);
   
   SendPayload(json);
  }

//+------------------------------------------------------------------+
void SendPayload(const string json)
  {
   if(MQLInfoInteger(MQL_TESTER)) { Print("[SignalRelay] tester mode -- skip WebRequest"); return; }
   
   string headers = "Content-Type: application/json\r\n" + "X-Signal-Secret: " + InpReceiverSecret + "\r\n";
   char data[];
   int  len = StringLen(json);
   StringToCharArray(json, data, 0, len, CP_UTF8);
   char   result[];
   string result_headers;
   
   int sent = WebRequest("POST", InpReceiverURL, headers, InpTimeoutMs, data, result, result_headers);
   if(sent == -1)
     {
      int err = GetLastError();
      string hint = (err == 4014) ? " -- WebRequest tidak diizinkan! Tambahkan URL di: Tools > Options > Expert Advisors > Allow WebRequest for listed URL" : "";
      Print("[SignalRelay] WebRequest GAGAL, error ", err, hint);
      return;
     }
   Print("[SignalRelay] OK, HTTP ", sent);
  }

//+------------------------------------------------------------------+
string BuildNotice(string text) { return StringFormat("{\"action\":\"NOTICE\",\"comment\":\"%s\",\"deal\":0}", JsonEscape(text)); }
string JsonEscape(string s)
  {
   StringReplace(s, "\\", "\\\\");
   StringReplace(s, "\"", "\\\"");
   StringReplace(s, "\n", "\\n");
   StringReplace(s, "\r", "");
   return s;
  }
bool IsProcessed(ulong ticket) { for(int i = 0; i < PROC_RING; i++) if(g_processed[i] == ticket) return true; return false; }
void MarkProcessed(ulong ticket) { g_processed[g_proc_count % PROC_RING] = ticket; g_proc_count++; }
//+------------------------------------------------------------------+
