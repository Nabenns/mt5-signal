//+------------------------------------------------------------------+
//|                                                  SignalRelay.mq5 |
//|                    MT5 → Telegram signal relay via VPS receiver  |
//+------------------------------------------------------------------+
#property copyright   "SignalRelay v3"
#property version     "3.00"
#description "Kirim notifikasi Telegram setiap posisi open/close (incl. SL/TP hit)."
#description "Attach ke SATU chart — event trade bersifat terminal-wide."
#description "V3: Compatible dengan MT5 build lama (WebRequest signature lama + URL query secret)."

//--- inputs ----------------------------------------------------------
input string InpReceiverURL    = "https://hirmes.bensserver.cloud/api/signal";   
input long   InpMagicFilter    = 0;     
input bool   InpNotifyStartup  = true;  
const string CFG_SECRET        = "3e0371e7c5673317fc134f192e0b7df4dc7a980e8b4fb610"; // hardcoded (jangan diubah)
const int    CFG_TIMEOUT       = 3000;  

//--- globals ---------------------------------------------------------
#define PROC_RING 128
ulong g_processed[PROC_RING];  
int   g_proc_count = 0;

//+------------------------------------------------------------------+
//| Initialization                                                    |
//+------------------------------------------------------------------+
int OnInit()
  {
   ArrayInitialize(g_processed, 0);
   Print("[SignalRelay v3] ready — receiver: ", InpReceiverURL,
         " | magic filter: ", (InpMagicFilter == 0 ? "SEMUA" : IntegerToString(InpMagicFilter)));

   if(InpNotifyStartup && !MQLInfoInteger(MQL_TESTER))
     {
      string msg = "\uD83E\uDD16 SignalRelay v3 ONLINE\nAkun: "
                   + IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN))
                   + "\nServer: " + AccountInfoString(ACCOUNT_SERVER);
      SendPayload(BuildNotice(msg));
     }
   return(INIT_SUCCEEDED);
  }

//+------------------------------------------------------------------+
//| Trade transaction handler                                          |
//+------------------------------------------------------------------+
void OnTradeTransaction(const MqlTradeTransaction& trans,
                        const MqlTradeRequest&    request,
                        const MqlTradeResult&     result)
  {
   if(trans.type != TRADE_TRANSACTION_DEAL_ADD)
      return;

   ulong ticket = trans.deal;
   if(ticket == 0)
      return;
   if(IsProcessed(ticket))
      return;
   if(!HistoryDealSelect(ticket))
      return;

   long deal_type = HistoryDealGetInteger(ticket, DEAL_TYPE);
   if(deal_type != DEAL_TYPE_BUY && deal_type != DEAL_TYPE_SELL)
      return;

   long entry    = HistoryDealGetInteger(ticket, DEAL_ENTRY);
   bool is_open  = (entry == DEAL_ENTRY_IN);
   bool is_close = (entry == DEAL_ENTRY_OUT || entry == DEAL_ENTRY_OUT_BY || entry == DEAL_ENTRY_INOUT);
   if(!is_open && !is_close)
      return;

   long magic = HistoryDealGetInteger(ticket, DEAL_MAGIC);
   if(InpMagicFilter > 0 && magic != InpMagicFilter)
      return;

   MarkProcessed(ticket);
   SendDealSignal(ticket, is_open, request);
  }

//+------------------------------------------------------------------+
//| Kumpulkan data deal → JSON → POST                                |
//+------------------------------------------------------------------+
void SendDealSignal(ulong ticket, bool is_open, const MqlTradeRequest& request)
  {
   string symbol  = HistoryDealGetString(ticket, DEAL_SYMBOL);
   long   dtype   = HistoryDealGetInteger(ticket, DEAL_TYPE);
   string side    = (dtype == DEAL_TYPE_BUY) ? "BUY" : "SELL";
   double volume  = HistoryDealGetDouble(ticket, DEAL_VOLUME);
   double price   = HistoryDealGetDouble(ticket, DEAL_PRICE);
   double profit  = HistoryDealGetDouble(ticket, DEAL_PROFIT)
                  + HistoryDealGetDouble(ticket, DEAL_SWAP)
                  + HistoryDealGetDouble(ticket, DEAL_COMMISSION);
   long   magic   = HistoryDealGetInteger(ticket, DEAL_MAGIC);
   string comment = HistoryDealGetString(ticket, DEAL_COMMENT);
   ulong  pos_id  = (ulong)HistoryDealGetInteger(ticket, DEAL_POSITION_ID);

   int digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
   if(digits <= 0)
      digits = 5;

   //--- SL/TP: coba dari posisi live dulu
   double sl = 0.0, tp = 0.0;
   if(pos_id > 0)
     {
      for(int i = PositionsTotal() - 1; i >= 0; i--)
        {
         ulong pid = PositionGetTicket(i);
         if(pid == pos_id && PositionSelectByTicket(pid))
           {
            sl = PositionGetDouble(POSITION_SL);
            tp = PositionGetDouble(POSITION_TP);
            break;
           }
        }
     }
   
   // Fallback ke history deal jika posisi tidak ditemukan lagi
   if((sl == 0 && tp == 0) && !is_open)
     {
      for(int j = HistoryDealsTotal() - 1; j >= 0 && j >= HistoryDealsTotal() - 200; j--)
        {
         long hticket = HistoryDealGetTicket(j);
         if(hticket == 0) continue;
         if(HistoryDealGetString(hticket, DEAL_SYMBOL) == symbol)
           {
            sl = HistoryDealGetDouble(hticket, DEAL_SL);
            tp = HistoryDealGetDouble(hticket, DEAL_TP);
            break;
           }
        }
     }

   if(sl == 0 && tp == 0 && is_open)
     {
      sl = request.sl;
      tp = request.tp;
     }

   string action = is_open ? "OPEN" : "CLOSE";
   string json = StringFormat(
      "{\"action\":\"%s\",\"symbol\":\"%s\",\"type\":\"%s\",\"lot\":%.2f,"
      "\"price\":%s,\"sl\":%s,\"tp\":%s,\"profit\":%.2f,\"magic\":%d,"
      "\"comment\":\"%s\",\"deal\":%llu,\"position\":%llu,\"digits\":%d}",
      action,
      JsonEscape(symbol),
      side,
      volume,
      DoubleToString(price, digits),
      DoubleToString(sl, digits),
      DoubleToString(tp, digits),
      is_open ? 0.0 : profit,
      (int)magic,
      JsonEscape(comment),
      ticket,
      pos_id,
      digits);

   SendPayload(json);
  }

//+------------------------------------------------------------------+
//| HTTP POST ke receiver (WebRequest — COMPATIBLE with old builds)  |
//+------------------------------------------------------------------+
void SendPayload(const string json)
  {
   if(MQLInfoInteger(MQL_TESTER))
     {
      Print("[SignalRelay v3] tester mode — skip WebRequest: ", json);
      return;
     }

   // Append secret to URL as query param (compatible with old MT5 builds that can't send custom headers)
   string full_url = InpReceiverURL;
   if(StringFind(full_url, "?") < 0)
      full_url += "?secret=" + CFG_SECRET;
   else
      full_url += "&secret=" + CFG_SECRET;

   char data[];
   int  len = StringLen(json);
   if(len > 0)
      StringToCharArray(json, data, 0, len, CP_UTF8);
   else
      ArraySize(data, 0);

   char   result[];
   string result_headers;
   
   // OLD WebRequest signature (compatible):
   // int WebRequest(string method, string url, string headers[], int timeout, char body[], int &body_len, char &response[], string &response_headers)
   // But untuk compatibility maksimal pakai signature minimal 7 params
   int sent = WebRequest("POST", full_url, "", CFG_TIMEOUT, 
                         data, len, result, result_headers);
                         
   if(sent == -1)
     {
      int err = GetLastError();
      string hint = "";
      if(err == 4014)
         hint = " — WebRequest tidak diizinkan! Tambahkan URL di: Tools > Options > Expert Advisors > Allow WebRequest for listed URL";
      Print("[SignalRelay v3] WebRequest GAGAL, error ", err, hint);
      return;
     }
   Print("[SignalRelay v3] terkirim. Response: ", CharArrayToString(result, 0, WHOLE_ARRAY, CP_UTF8));
  }

//+------------------------------------------------------------------+
//| Helpers                                                           |
//+------------------------------------------------------------------+
string BuildNotice(string text)
  {
   return StringFormat("{\"action\":\"NOTICE\",\"comment\":\"%s\",\"deal\":0}",
                       JsonEscape(text));
  }

string JsonEscape(string s)
  {
   StringReplace(s, "\\", "\\\\");
   StringReplace(s, "\"", "\\\"");
   StringReplace(s, "\n", "\\n");
   StringReplace(s, "\r", "");
   return s;
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
//+------------------------------------------------------------------+
