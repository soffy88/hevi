import json
import sys
import os
from hevi.toonflow.asset_bible import AssetBible

def handle_mcp_stdio():
    # Simple stdio JSON-RPC bridge for MCP compatibility test
    bible = AssetBible()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            req_id = req.get("id")
            method = req.get("method")
            params = req.get("params", {})
            
            if method == "initialize":
                res = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "protocolVersion": "2025-03-26",
                        "capabilities": {"tools": {}, "resources": {}},
                        "serverInfo": {"name": "hevi-toonflow-mcp", "version": "1.0.0"}
                    }
                }
            elif method == "tools/list":
                res = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "tools": [
                            {
                                "name": "getAppState",
                                "description": "Get current application state and workspace info",
                                "inputSchema": {"type": "object", "properties": {}}
                            },
                            {
                                "name": "registerAsset",
                                "description": "Register character/scene in asset bible",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {
                                        "type": {"type": "string"},
                                        "name": {"type": "string"},
                                        "appearance": {"type": "string"},
                                        "palette": {"type": "array", "items": {"type": "string"}}
                                    },
                                    "required": ["type", "name"]
                                }
                            },
                            {
                                "name": "checkConsistency",
                                "description": "Check character color consistency across shots",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {
                                        "shot_id": {"type": "string"},
                                        "character": {"type": "string"},
                                        "observed_palette": {"type": "array", "items": {"type": "string"}}
                                    },
                                    "required": ["shot_id", "character", "observed_palette"]
                                }
                            }
                        ]
                    }
                }
            elif method == "tools/call":
                name = params.get("name")
                args = params.get("arguments", {})
                if name == "getAppState":
                    output = {"status": "ok", "workspace": os.getcwd(), "activeCanvas": "default"}
                elif name == "registerAsset":
                    if args.get("type") == "character":
                        bible.register_character(args["name"], args.get("appearance", ""), [], args.get("palette", []), [])
                    output = {"success": True, "registered": args.get("name")}
                elif name == "checkConsistency":
                    output = bible.check_consistency(args["shot_id"], args["character"], args["observed_palette"])
                else:
                    output = {"error": f"Unknown tool {name}"}
                
                res = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": json.dumps(output, ensure_ascii=False)}],
                        "structuredContent": output
                    }
                }
            else:
                res = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": f"Method not found: {method}"}
                }
            print(json.dumps(res, ensure_ascii=False))
            sys.stdout.flush()
        except Exception as e:
            err_res = {"jsonrpc": "2.0", "id": None, "error": {"code": -32603, "message": str(e)}}
            print(json.dumps(err_res, ensure_ascii=False))
            sys.stdout.flush()

if __name__ == "__main__":
    handle_mcp_stdio()
