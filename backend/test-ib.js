const { IBApi, EventName } = require("@stoqey/ib");

const ib = new IBApi({ host: "127.0.0.1", port: 4002, clientId: 1 });

ib.on(EventName.connected, () => console.log("✅ Conectado a IB Gateway"))
  .on(EventName.error, (err, code, reqId) =>
      console.error("❌", code, err.message, "reqId:", reqId))
  .on(EventName.accountSummary, (reqId, account, tag, value, currency) =>
      console.log(account, tag, value, currency))
  .on(EventName.accountSummaryEnd, () => { ib.disconnect(); process.exit(0); });

ib.connect();
ib.reqAccountSummary(9001, "All", "NetLiquidation,TotalCashValue,BuyingPower");