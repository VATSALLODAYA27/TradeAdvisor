"""Deliverable 3: the output schema from the PRD as Pydantic models. Instructor uses them to constrain and validate the model."""
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

Short = Field(..., max_length=600)  # 1-3 short sentences


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MacroVerdict(Strict):
    regime: Literal["Bullish", "Bearish", "Neutral"]
    breadth_summary: str = Short
    rationale: str = Short


class MutualFundOrder(Strict):
    fund_name: str
    action: Literal["BUY", "SELL", "HOLD"]
    amount_inr: Optional[float]
    reason: str = Short


class StockDecision(Strict):
    ticker: str
    strategy_sleeve: Literal["Weekly Core", "Daily Tactical"]
    conviction: Literal["High", "Moderate", "Veto"]
    entry_price: Optional[float]
    stop_loss_price: Optional[float]
    technical_rationale: str = Short
    fundamental_catalyst: str = Short
    downside_risks: str = Short


class PortfolioExit(Strict):
    ticker: str
    exit_trigger: str


class DeskOutput(Strict):
    macro_verdict: MacroVerdict
    mutual_fund_rebalance_orders: List[MutualFundOrder]
    stock_trade_decisions: List[StockDecision]
    portfolio_exits: List[PortfolioExit]
    compliance_disclaimer: str
