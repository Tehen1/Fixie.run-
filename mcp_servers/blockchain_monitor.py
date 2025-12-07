#!/usr/bin/env python3
"""
Blockchain Monitor MCP Server
Surveillance smart contracts et événements on-chain
Transport: stdio
Integration: Web3.py + Viem
"""

import asyncio
import json
from typing import Dict, List, Optional
from datetime import datetime
import sys

try:
    from web3 import Web3
    from web3.middleware import geth_poa_middleware
except ImportError:
    print("Error: web3 package not found. Install with: pip install web3", file=sys.stderr)
    sys.exit(1)

try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent
except ImportError:
    print("Error: mcp package not found. Install with: pip install mcp", file=sys.stderr)
    sys.exit(1)

# Contract ABIs (simplified)
FIXIE_TOKEN_ABI = [
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "from", "type": "address"},
            {"indexed": True, "name": "to", "type": "address"},
            {"indexed": False, "name": "value", "type": "uint256"}
        ],
        "name": "Transfer",
        "type": "event"
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "user", "type": "address"},
            {"indexed": False, "name": "amount", "type": "uint256"},
            {"indexed": False, "name": "timestamp", "type": "uint256"}
        ],
        "name": "Staked",
        "type": "event"
    }
]

class BlockchainMonitor:
    def __init__(self):
        self.providers = {
            "polygon-zkevm": Web3(Web3.HTTPProvider("https://zkevm-rpc.com")),
            "scroll": Web3(Web3.HTTPProvider("https://rpc.scroll.io")),
            "zksync": Web3(Web3.HTTPProvider("https://mainnet.era.zksync.io"))
        }
        
        # Add PoA middleware for compatibility
        for provider in self.providers.values():
            provider.middleware_onion.inject(geth_poa_middleware, layer=0)
        
        self.event_cache = []
    
    async def monitor_events(
        self, 
        contract_address: str, 
        chain: str = "polygon-zkevm",
        event_name: str = "Transfer",
        from_block: int = None
    ) -> Dict:
        """Monitor smart contract events"""
        try:
            w3 = self.providers.get(chain)
            if not w3:
                return {"error": f"Unsupported chain: {chain}"}
            
            if not w3.is_connected():
                return {"error": f"Failed to connect to {chain}"}
            
            # Validate address
            if not Web3.is_address(contract_address):
                return {"error": f"Invalid contract address: {contract_address}"}
            
            contract_address = Web3.to_checksum_address(contract_address)
            contract = w3.eth.contract(address=contract_address, abi=FIXIE_TOKEN_ABI)
            
            # Get current block
            current_block = w3.eth.block_number
            from_block = from_block or (current_block - 1000)  # Last 1000 blocks
            
            # Get event filter
            event_filter = None
            if event_name == "Transfer":
                event_filter = contract.events.Transfer.create_filter(fromBlock=from_block)
            elif event_name == "Staked":
                event_filter = contract.events.Staked.create_filter(fromBlock=from_block)
            else:
                return {"error": f"Unknown event: {event_name}"}
            
            # Fetch events
            events = event_filter.get_all_entries()
            
            result = {
                "chain": chain,
                "contract": contract_address,
                "event_name": event_name,
                "from_block": from_block,
                "to_block": current_block,
                "events_count": len(events),
                "events": []
            }
            
            for event in events[-50:]:  # Limit to last 50 events
                result["events"].append({
                    "block_number": event["blockNumber"],
                    "transaction_hash": event["transactionHash"].hex(),
                    "args": dict(event["args"]),
                    "timestamp": datetime.now().isoformat()
                })
            
            return result
            
        except Exception as e:
            return {"error": str(e), "chain": chain}
    
    async def check_vulnerabilities(self, contract_address: str, chain: str = "polygon-zkevm") -> Dict:
        """Basic smart contract security checks"""
        try:
            w3 = self.providers.get(chain)
            if not w3 or not w3.is_connected():
                return {"error": f"Connection failed to {chain}"}
            
            contract_address = Web3.to_checksum_address(contract_address)
            
            # Get contract bytecode
            bytecode = w3.eth.get_code(contract_address).hex()
            
            vulnerabilities = []
            warnings = []
            
            # Check 1: Contract exists
            if bytecode == "0x":
                return {"error": "No contract found at this address"}
            
            # Check 2: Selfdestruct opcode (0xff)
            if "ff" in bytecode:
                vulnerabilities.append({
                    "severity": "HIGH",
                    "type": "SELFDESTRUCT",
                    "description": "Contract contains SELFDESTRUCT opcode - can be destroyed"
                })
            
            # Check 3: Delegatecall (0xf4)
            if "f4" in bytecode:
                warnings.append({
                    "severity": "MEDIUM",
                    "type": "DELEGATECALL",
                    "description": "Contract uses DELEGATECALL - ensure proper access control"
                })
            
            # Check 4: Contract size
            bytecode_size = len(bytecode) // 2  # Convert hex to bytes
            if bytecode_size > 24576:  # 24KB limit
                warnings.append({
                    "severity": "LOW",
                    "type": "SIZE_LIMIT",
                    "description": f"Contract size ({bytecode_size} bytes) exceeds recommended limit"
                })
            
            return {
                "chain": chain,
                "contract": contract_address,
                "bytecode_size": bytecode_size,
                "vulnerabilities": vulnerabilities,
                "warnings": warnings,
                "scan_timestamp": datetime.now().isoformat(),
                "recommendation": "Run full audit with Slither or Mythril for production contracts"
            }
            
        except Exception as e:
            return {"error": str(e)}
    
    async def track_transactions(
        self, 
        address: str, 
        chain: str = "polygon-zkevm",
        tx_count: int = 10
    ) -> Dict:
        """Track recent transactions for an address"""
        try:
            w3 = self.providers.get(chain)
            if not w3 or not w3.is_connected():
                return {"error": f"Connection failed to {chain}"}
            
            address = Web3.to_checksum_address(address)
            
            # Get transaction count
            nonce = w3.eth.get_transaction_count(address)
            
            # Get balance
            balance_wei = w3.eth.get_balance(address)
            balance_eth = w3.from_wei(balance_wei, 'ether')
            
            # Get current block for recent transactions scan
            current_block = w3.eth.block_number
            
            transactions = []
            # Scan last 100 blocks for transactions
            for block_num in range(current_block, max(current_block - 100, 0), -1):
                block = w3.eth.get_block(block_num, full_transactions=True)
                for tx in block.transactions:
                    if tx['from'] == address or tx['to'] == address:
                        transactions.append({
                            "hash": tx['hash'].hex(),
                            "from": tx['from'],
                            "to": tx['to'],
                            "value": str(w3.from_wei(tx['value'], 'ether')),
                            "block": block_num,
                            "gas_price": str(w3.from_wei(tx.get('gasPrice', 0), 'gwei')),
                            "type": "sent" if tx['from'] == address else "received"
                        })
                        
                        if len(transactions) >= tx_count:
                            break
                
                if len(transactions) >= tx_count:
                    break
            
            return {
                "chain": chain,
                "address": address,
                "balance_eth": str(balance_eth),
                "transaction_count": nonce,
                "recent_transactions": transactions[:tx_count],
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            return {"error": str(e)}

# MCP Server Setup
app = Server("blockchain-monitor")
monitor = BlockchainMonitor()

@app.list_tools()
async def list_tools() -> List[Tool]:
    return [
        Tool(
            name="monitor_events",
            description="Monitor smart contract events (Transfer, Staked, etc.). Fetches recent events from specified contract.",
            inputSchema={
                "type": "object",
                "properties": {
                    "contract_address": {
                        "type": "string",
                        "description": "Smart contract address (0x...)"
                    },
                    "chain": {
                        "type": "string",
                        "enum": ["polygon-zkevm", "scroll", "zksync"],
                        "default": "polygon-zkevm"
                    },
                    "event_name": {
                        "type": "string",
                        "enum": ["Transfer", "Staked"],
                        "default": "Transfer"
                    },
                    "from_block": {
                        "type": "integer",
                        "description": "Starting block number (default: current - 1000)"
                    }
                },
                "required": ["contract_address"]
            }
        ),
        Tool(
            name="check_vulnerabilities",
            description="Perform basic security checks on smart contract bytecode. Detects selfdestruct, delegatecall, and size issues.",
            inputSchema={
                "type": "object",
                "properties": {
                    "contract_address": {
                        "type": "string",
                        "description": "Smart contract address to audit"
                    },
                    "chain": {
                        "type": "string",
                        "enum": ["polygon-zkevm", "scroll", "zksync"],
                        "default": "polygon-zkevm"
                    }
                },
                "required": ["contract_address"]
            }
        ),
        Tool(
            name="track_transactions",
            description="Track recent transactions for a wallet address. Returns balance and transaction history.",
            inputSchema={
                "type": "object",
                "properties": {
                    "address": {
                        "type": "string",
                        "description": "Wallet address to track"
                    },
                    "chain": {
                        "type": "string",
                        "enum": ["polygon-zkevm", "scroll", "zksync"],
                        "default": "polygon-zkevm"
                    },
                    "tx_count": {
                        "type": "integer",
                        "default": 10,
                        "description": "Number of recent transactions to fetch"
                    }
                },
                "required": ["address"]
            }
        )
    ]

@app.call_tool()
async def call_tool(name: str, arguments: Dict) -> List[TextContent]:
    if name == "monitor_events":
        result = await monitor.monitor_events(
            contract_address=arguments["contract_address"],
            chain=arguments.get("chain", "polygon-zkevm"),
            event_name=arguments.get("event_name", "Transfer"),
            from_block=arguments.get("from_block")
        )
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    
    elif name == "check_vulnerabilities":
        result = await monitor.check_vulnerabilities(
            contract_address=arguments["contract_address"],
            chain=arguments.get("chain", "polygon-zkevm")
        )
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    
    elif name == "track_transactions":
        result = await monitor.track_transactions(
            address=arguments["address"],
            chain=arguments.get("chain", "polygon-zkevm"),
            tx_count=arguments.get("tx_count", 10)
        )
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    
    else:
        return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]

if __name__ == "__main__":
    asyncio.run(stdio_server(app))
