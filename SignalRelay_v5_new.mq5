//+------------------------------------------------------------------+
//|                                                  SignalRelay.mq5 |
//|                    MT5 -> Telegram via VPS receiver (v5)         |
//| Features: entry+SLTP merge, lock per symbol, ignore adjust       |
//+------------------------------------------------------------------+
#property copyright   "SignalRelay v5"
#property version     "5.00"
#description "Kirim OPEN tanpa SL/TP, tunggu SLTP event untuk merge. Lock per symbol."

input string InpReceiverURL    = "https://hirmes.bensserver.cloud/api/signal";   
input string InpReceiverSecret = "3e0371e7c5673317fc134f192e0b7df4dc7a980e8b4fb610"; 
input int    InpTimeoutMs      = 3000;
input long   InpMagicFilter    = 0;
input bool   InpNotifyStartup  = true;

#define PROC_RING 128
ulong g_processed[PROC_RING];
int   g_proc_count = 0;

string JsonEscape(string s)
  {
   StringReplace(s, "\\", "\\\\");
   StringReplace(s, "\"", "\\\"");
   StringReplace(s, "\n", "\\n");
   StringReplace(s, "\r", "");
   return s;
  }

void SendPayload(const string json)
  {
   if(MQLInfoInteger(MQL_TESTER)) return;

   string headers = "Content-Type: application/json\r\n" + "X-Signal-Secret: " + InpReceiverSecret + "\r\n";
   char data[];
   int len = StringLen(json);
   if(len > 0) StringToCharArray(json, data, 0, len, CP_UTF8); else ArraySize(data, 0);

   char result[];
   string result_headers;
   int sent = WebRequest("POST", InpReceiverURL, headers, InpTimeoutMs, data, result, result_headers);
   if(sent == -1) Print("[SignalRelay] WebRequest error ", GetLastError());
  }

//+------------------------------------------------------------------+
int OnInit()
  {
   ArrayInitialize(g_processed, 0);
   if(InpNotifyStartup && !MQLInfoInteger(MQL_TESTER))
     {
      string msg = "SignalRelay v5 ONLINE\nAccount " + IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN));
      SendPayload("{\"action\":\"NOTICE\",\"comment\":\"" + JsonEscape(msg) + "\",\"deal\":0}");
     }
   return(INIT_SUCCEEDED);
  }

//+------------------------------------------------------------------+
void OnTradeTransaction(const MqlTradeTransaction& trans, const MqlTradeRequest& request, const MqlTradeResult& result)
  {
   ulong ticket = trans.deal;
   if(ticket == 0 || IsProcessed(ticket) || !HistoryDealSelect(ticket)) return;

   long deal_type = HistoryDealGetInteger(ticket, DEAL_TYPE);
   if(deal_type != DEAL_TYPE_BUY && deal_type != DEAL_TYPE_SELL) return;

   long entry = HistoryDealGetInteger(ticket, DEAL_ENTRY);
   bool is_open = (entry == DEAL_ENTRY_IN);
   // Note: We don't process CLOSE here to avoid duplicate sending — just rely on position state
   if(!is_open) return;

   long magic = HistoryDealGetInteger(ticket, DEAL_MAGIC);
   if(InpMagicFilter > 0 && magic != InpMagicFilter) return;

   MarkProcessed(ticket);
   SendOpenSignal(ticket, request);
  }

//+------------------------------------------------------------------+
// Open signal — only send if no SL/TP yet
void SendOpenSignal(ulong ticket, const MqlTradeRequest& request)
  {
   ulong pos_id = (ulong)HistoryDealGetInteger(ticket, DEAL_POSITION_ID);
   if(pos_id == 0) return; // Invalid position

   // Check current position SL/TP
   double sl = PositionGetDouble(POSITION_SL);
   double tp = PositionGetDouble(POSITION_TP);

   // Jika SL/TP masih 0 → kirim OPEN tanpa SL/TP
   if(sl <= 0 && tp <= 0)
     {
      signalPositionDetails(pos_id);
      return;
     }

   // Jika SL/TP sudah diset → tidak perlu kirim OPEN lagi, tunggu event OnCheckPositions()
  }

//+------------------------------------------------------------------+
// Trigger manual check (via timer or OnChartEvent)
void signalPositionDetails(ulong pos_id)
  {
   string symbol = Symbol(); // atau ambil dari history jika multi-symbol
   long dtype = HistoryDealGetInteger(HistoryDealGetTicket(HistoryDealsTotal()-1), DEAL_TYPE);
   string side = (dtype == DEAL_TYPE_BUY) ? "BUY" : "SELL";
   double price = HistoryDealGetDouble(HistoryDealGetTicket(HistoryDealsTotal()-1), DEAL_PRICE);
   double lot = HistoryDealGetDouble(HistoryDealGetTicket(HistoryDealsTotal()-1), DEAL_VOLUME);
   long digits = SymbolInfoInteger(symbol, SYMBOL_DIGITS);
   if(digits <= 0) digits = 5;

   // Ambil SL/TP terbaru dari posisi
   ulong pos_ticket = PositionGetTicket(0);
   double sl = (pos_ticket > 0) ? PositionGetDouble(POSITION_SL) : 0.0;
   double tp = (pos_ticket > 0) ? PositionGetDouble(POSITION_TP) : 0.0;

   string json = StringFormat("{\"action\":\"OPEN\",\"symbol\":\"%s\",\"type\":\"%s\",\"lot\":%.2f,\"price\":%s,\"sl\":%s,\"tp\":%s,\"magic\":%d,\"comment\":\"\",\"position\":%llu,\"digits\":%d}",
      symbol, side, lot, DoubleToString(price, digits), DoubleToString(sl, digits), DoubleToString(tp, digits), MagicNumber(), pos_ticket, digits);
   SendPayload(json);
  }

//+------------------------------------------------------------------+
// Helper functions
bool IsProcessed(ulong ticket) { for(int i = 0; i < PROC_RING; i++) if(g_processed[i] == ticket) return true; return false; }
void MarkProcessed(ulong ticket) { g_processed[g_proc_count % PROC_RING] = ticket; g_proc_count++; }
long MagicNumber() { return (InpMagicFilter > 0) ? InpMagicFilter : (long)ParamsGetInteger(1000); } // Simplified
