#!/usr/bin/env python3
"""
Web3 Data Aggregator MCP Server
Agrège données blockchain multi-sources (DeFiLlama, CoinGecko, zkEVM RPC)
Transport: stdio
"""

import asyncio
import aiohttp
import json
from datetime import datetime
from typing import Dict, List, Optional
import sys

# FastMCP pour Model Context Protocol
try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent
except ImportError:
    print("Error: mcp package not found. Install with: pip install mcp", file=sys.stderr)
    sys.exit(1)

# Configuration
DEFILLAMA_BASE_URL = "https://api.llama.fi"
COINGECKO_BASE_URL = "https://api.coingecko.com/api/v3"
ZKEVM_RPC_URL = "https://zkevm-rpc.com"

class Web3Aggregator:
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self.cache: Dict = {}
        
    async def __aenter__(self):
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30),
            headers={"User-Agent": "FixieRun-MCP/1.0"}
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def fetch_tvl(self, protocol: str = "all") -> Dict:
        """Fetch Total Value Locked from DeFiLlama"""
        try:
            cache_key = f"tvl_{protocol}"
            if cache_key in self.cache:
                cached_time, data = self.cache[cache_key]
                if (datetime.now() - cached_time).seconds < 3600:  # 1h cache
                    return data
            
            if protocol == "all":
                url = f"{DEFILLAMA_BASE_URL}/tvl"
            else:
                url = f"{DEFILLAMA_BASE_URL}/protocol/{protocol}"
            
            async with self.session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    self.cache[cache_key] = (datetime.now(), data)
                    return data
                else:
                    return {"error": f"HTTP {response.status}", "protocol": protocol}
        except Exception as e:
            return {"error": str(e), "protocol": protocol}
    
    async def get_protocol_data(self, protocol_name: str) -> Dict:
        """Get detailed protocol data from DeFiLlama"""
        try:
            url = f"{DEFILLAMA_BASE_URL}/protocol/{protocol_name}"
            async with self.session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    return {
                        "name": data.get("name"),
                        "symbol": data.get("symbol"),
                        "tvl": data.get("tvl"),
                        "chainTvls": data.get("chainTvls", {}),
                        "change_1h": data.get("change_1h"),
                        "change_1d": data.get("change_1d"),
                        "change_7d": data.get("change_7d"),
                        "mcap": data.get("mcap")
                    }
                else:
                    return {"error": f"Protocol {protocol_name} not found"}
        except Exception as e:
            return {"error": str(e)}
    
    async def query_blockchain(self, chain: str = "polygon-zkevm", method: str = "eth_blockNumber") -> Dict:
        """Query blockchain RPC endpoints"""
        try:
            rpc_urls = {
                "polygon-zkevm": "https://zkevm-rpc.com",
                "scroll": "https://rpc.scroll.io",
                "zksync": "https://mainnet.era.zksync.io"
            }
            
            rpc_url = rpc_urls.get(chain, ZKEVM_RPC_URL)
            
            payload = {
                "jsonrpc": "2.0",
                "method": method,
                "params": [],
                "id": 1
            }
            
            async with self.session.post(rpc_url, json=payload) as response:
                if response.status == 200:
                    data = await response.json()
                    return {
                        "chain": chain,
                        "method": method,
                        "result": data.get("result"),
                        "block_number": int(data.get("result", "0x0"), 16) if method == "eth_blockNumber" else None
                    }
                else:
                    return {"error": f"RPC call failed: {response.status}"}
        except Exception as e:
            return {"error": str(e), "chain": chain}
    
    async def get_token_price(self, token_id: str = "ethereum") -> Dict:
        """Get token price from CoinGecko"""
        try:
            cache_key = f"price_{token_id}"
            if cache_key in self.cache:
                cached_time, data = self.cache[cache_key]
                if (datetime.now() - cached_time).seconds < 300:  # 5min cache
                    return data
            
            url = f"{COINGECKO_BASE_URL}/simple/price"
            params = {
                "ids": token_id,
                "vs_currencies": "usd",
                "include_24hr_change": "true",
                "include_market_cap": "true"
            }
            
            async with self.session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    result = {
                        "token": token_id,
                        "price_usd": data.get(token_id, {}).get("usd"),
                        "change_24h": data.get(token_id, {}).get("usd_24h_change"),
                        "market_cap": data.get(token_id, {}).get("usd_market_cap"),
                        "timestamp": datetime.now().isoformat()
                    }
                    self.cache[cache_key] = (datetime.now(), result)
                    return result
                else:
                    return {"error": f"CoinGecko API error: {response.status}"}
        except Exception as e:
            return {"error": str(e)}

# MCP Server Setup
app = Server("web3-aggregator")
aggregator = Web3Aggregator()

@app.list_tools()
async def list_tools() -> List[Tool]:
    return [
        Tool(
            name="fetch_tvl",
            description="Fetch Total Value Locked (TVL) data from DeFiLlama. Use 'all' for global TVL or specify a protocol name.",
            inputSchema={
                "type": "object",
                "properties": {
                    "protocol": {
                        "type": "string",
                        "description": "Protocol name (e.g., 'aave', 'uniswap') or 'all' for global TVL",
                        "default": "all"
                    }
                }
            }
        ),
        Tool(
            name="get_protocol_data",
            description="Get detailed data for a specific DeFi protocol including TVL breakdown by chain, price changes, and market cap.",
            inputSchema={
                "type": "object",
                "properties": {
                    "protocol_name": {
                        "type": "string",
                        "description": "Protocol slug (e.g., 'aave', 'curve', 'uniswap')"
                    }
                },
                "required": ["protocol_name"]
            }
        ),
        Tool(
            name="query_blockchain",
            description="Query blockchain RPC endpoints for real-time data (block number, gas price, etc.). Supports Polygon zkEVM, Scroll, zkSync.",
            inputSchema={
                "type": "object",
                "properties": {
                    "chain": {
                        "type": "string",
                        "enum": ["polygon-zkevm", "scroll", "zksync"],
                        "description": "Blockchain network to query",
                        "default": "polygon-zkevm"
                    },
                    "method": {
                        "type": "string",
                        "description": "RPC method (e.g., 'eth_blockNumber', 'eth_gasPrice')",
                        "default": "eth_blockNumber"
                    }
                }
            }
        ),
        Tool(
            name="get_token_price",
            description="Get current token price and 24h change from CoinGecko. Returns USD price, market cap, and price change.",
            inputSchema={
                "type": "object",
                "properties": {
                    "token_id": {
                        "type": "string",
                        "description": "CoinGecko token ID (e.g., 'ethereum', 'bitcoin', 'polygon-zkevm')",
                        "default": "ethereum"
                    }
                }
            }
        )
    ]

@app.call_tool()
async def call_tool(name: str, arguments: Dict) -> List[TextContent]:
    async with aggregator:
        if name == "fetch_tvl":
            protocol = arguments.get("protocol", "all")
            result = await aggregator.fetch_tvl(protocol)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        
        elif name == "get_protocol_data":
            protocol_name = arguments.get("protocol_name")
            if not protocol_name:
                return [TextContent(type="text", text=json.dumps({"error": "protocol_name required"}))]
            result = await aggregator.get_protocol_data(protocol_name)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        
        elif name == "query_blockchain":
            chain = arguments.get("chain", "polygon-zkevm")
            method = arguments.get("method", "eth_blockNumber")
            result = await aggregator.query_blockchain(chain, method)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        
        elif name == "get_token_price":
            token_id = arguments.get("token_id", "ethereum")
            result = await aggregator.get_token_price(token_id)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        
        else:
            return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]

if __name__ == "__main__":
    # Run MCP server with stdio transport
    asyncio.run(stdio_server(app))
