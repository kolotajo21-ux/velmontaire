"""
MT5 connector placeholder for Linux/Render.

MetaTrader5 Python package requires a Windows environment with
the MetaTrader 5 terminal installed. Live MT5 connection is
therefore disabled in the Render demo.
"""

def get_mt5_status():
    return {
        "connected": False,
        "mode": "render_demo",
        "message": "MT5 connection is disabled in the Render demo."
    }
