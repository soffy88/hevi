"""Mock aiohttp — verify RestClient parse + error handling."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from oskill.exchange.okx_demo import OKXClientError, OKXDemoRestClient


@pytest.fixture
def client():
    return OKXDemoRestClient(
        api_key="k",
        api_secret="s",
        passphrase="p",
        api_base="https://test.okx.com",
    )


def _mock_session(status: int, json_data: dict | None = None, text_data: str = ""):
    mock_response = AsyncMock()
    mock_response.status = status
    mock_response.json = AsyncMock(return_value=json_data or {})
    mock_response.text = AsyncMock(return_value=text_data)

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_response)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.post = MagicMock(return_value=mock_ctx)
    mock_session.get = MagicMock(return_value=mock_ctx)

    mock_session_ctx = MagicMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

    return mock_session_ctx


@pytest.mark.asyncio
async def test_submit_order_success(client):
    mock_response = {
        "code": "0",
        "msg": "",
        "data": [{"ordId": "12345", "clOrdId": "test-1", "sCode": "0", "sMsg": ""}],
        "inTime": 1700000000,
        "outTime": 1700000001,
    }
    with patch("aiohttp.ClientSession", return_value=_mock_session(200, mock_response)):
        result = await client.submit_order(
            inst_id="BTC-USDT",
            side="buy",
            size_in_base=0.001,
            cl_ord_id="test-1",
        )

    assert result.code == "0"
    assert result.data[0]["ordId"] == "12345"
    assert result.in_time == 1700000000


@pytest.mark.asyncio
async def test_submit_order_rejected(client):
    mock_response = {
        "code": "1",
        "msg": "Operation failed",
        "data": [{"sCode": "51008", "sMsg": "Order failed: insufficient balance"}],
    }
    with patch("aiohttp.ClientSession", return_value=_mock_session(200, mock_response)):
        result = await client.submit_order(
            inst_id="BTC-USDT",
            side="buy",
            size_in_base=0.001,
        )

    assert result.code == "1"
    assert "insufficient balance" in result.data[0]["sMsg"]


@pytest.mark.asyncio
async def test_submit_order_http_error(client):
    with patch("aiohttp.ClientSession", return_value=_mock_session(500, text_data="Server Error")):
        with pytest.raises(OKXClientError, match="HTTP 500"):
            await client.submit_order(
                inst_id="BTC-USDT",
                side="buy",
                size_in_base=0.001,
            )


@pytest.mark.asyncio
async def test_missing_credentials():
    with pytest.raises(ValueError, match="required"):
        OKXDemoRestClient(api_key="", api_secret="s", passphrase="p")


@pytest.mark.asyncio
async def test_get_account_balance_success(client):
    mock_response = {
        "code": "0",
        "msg": "",
        "data": [
            {
                "totalEq": "100000.5",
                "uTime": "1700000000",
                "details": [
                    {"ccy": "USDT", "availBal": "95000.0"},
                    {"ccy": "BTC", "availBal": "0.5"},
                ],
            }
        ],
    }
    with patch("aiohttp.ClientSession", return_value=_mock_session(200, mock_response)):
        snapshot = await client.get_account_balance()

    assert snapshot.total_eq_usd == 100000.5
    assert snapshot.available_balance["USDT"] == 95000.0
    assert snapshot.available_balance["BTC"] == 0.5
