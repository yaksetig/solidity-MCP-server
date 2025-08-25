import os
import subprocess
import tempfile
import json
from typing import Any
import uvicorn
import asyncio
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

# Get port from Railway's environment variable
port = int(os.environ.get("PORT", 8080))

app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Constants
APP_DIR = os.path.dirname(os.path.abspath(__file__))
NODE_MODULES_PATH = os.path.join(APP_DIR, "node_modules")

# Define tools schema
TOOLS_SCHEMA = [
    {
        "name": "compile_solidity",
        "description": "Compile Solidity code and return compilation results",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "The Solidity source code as text"
                },
                "filename": {
                    "type": "string",
                    "description": "Optional filename for the contract",
                    "default": "Contract.sol"
                }
            },
            "required": ["code"]
        }
    },
    {
        "name": "security_audit",
        "description": "Run Slither security analysis on Solidity code",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "The Solidity source code as text"
                },
                "filename": {
                    "type": "string",
                    "description": "Optional filename for the contract",
                    "default": "Contract.sol"
                }
            },
            "required": ["code"]
        }
    },
    {
        "name": "compile_and_audit",
        "description": "Complete workflow: compile Solidity code then run security audit",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "The Solidity source code as text"
                },
                "filename": {
                    "type": "string",
                    "description": "Optional filename for the contract",
                    "default": "Contract.sol"
                }
            },
            "required": ["code"]
        }
    }
]

# Global request handler
request_handler = None

class MCPRequestHandler:
    def __init__(self):
        self.initialized = False
    
    async def handle_request(self, request_data: dict) -> dict:
        method = request_data.get("method")
        params = request_data.get("params", {})
        request_id = request_data.get("id")
        
        print(f"Handling MCP request: {method} (ID: {request_id})")
        
        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "tools": {}
                    },
                    "serverInfo": {
                        "name": "solidity-mcp-server",
                        "version": "1.0.0"
                    }
                }
            }
        
        elif method == "notifications/initialized":
            self.initialized = True
            print("MCP client initialized")
            return None  # Notifications don't need responses
        
        elif method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "tools": TOOLS_SCHEMA
                }
            }
        
        elif method == "tools/call":
            if not self.initialized:
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32002,
                        "message": "Server not initialized"
                    }
                }
            
            tool_name = params.get("name")
            arguments = params.get("arguments", {})
            
            print(f"Calling tool: {tool_name}")
            
            try:
                if tool_name == "compile_solidity":
                    result = await compile_solidity(
                        arguments.get("code"), 
                        arguments.get("filename", "Contract.sol")
                    )
                elif tool_name == "security_audit":
                    result = await security_audit(
                        arguments.get("code"),
                        arguments.get("filename", "Contract.sol")
                    )
                elif tool_name == "compile_and_audit":
                    result = await compile_and_audit(
                        arguments.get("code"),
                        arguments.get("filename", "Contract.sol")
                    )
                else:
                    return {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {
                            "code": -32601,
                            "message": f"Unknown tool: {tool_name}"
                        }
                    }

                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(result, indent=2)
                            }
                        ],
                        "isError": not result.get("success", False)
                    }
                }
                
            except Exception as e:
                print(f"Tool execution error: {str(e)}")
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32603,
                        "message": f"Tool execution failed: {str(e)}"
                    }
                }
        
        else:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32601,
                    "message": f"Method not found: {method}"
                }
            }

# SSE endpoint - this is what Claude connects to
@app.get("/sse")
async def sse_endpoint(request: Request):
    """SSE endpoint for MCP communication"""
    global request_handler
    request_handler = MCPRequestHandler()
    
    async def event_stream():
        # Send ready signal
        yield f"event: message\ndata: {json.dumps({'type': 'server_ready'})}\n\n"
        
        while True:
            try:
                # In a real SSE implementation, you'd read from the request body
                # For now, we'll just send keepalives
                await asyncio.sleep(30)
                yield f"event: ping\ndata: {json.dumps({'type': 'keepalive'})}\n\n"
            except Exception as e:
                print(f"SSE error: {e}")
                break
    
    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "*",
        }
    )

# POST endpoint for MCP requests over SSE
@app.post("/sse")
async def handle_sse_request(request: Request):
    """Handle MCP requests sent to SSE endpoint"""
    global request_handler
    
    if not request_handler:
        request_handler = MCPRequestHandler()
    
    try:
        body = await request.json()
        print(f"SSE POST request: {body}")
        
        response = await request_handler.handle_request(body)
        
        if response is None:
            # Notification - no response needed
            return {"status": "ok"}
        
        return response
        
    except Exception as e:
        print(f"SSE request handling error: {str(e)}")
        return {
            "jsonrpc": "2.0",
            "id": body.get("id") if 'body' in locals() else None,
            "error": {
                "code": -32603,
                "message": f"Internal error: {str(e)}"
            }
        }

# Root endpoint
@app.get("/")
async def root():
    return {
        "name": "Solidity MCP Server",
        "version": "1.0.0",
        "transport": "sse",
        "endpoint": "/sse"
    }

# Health check
@app.get("/health")
async def health():
    return {"status": "healthy"}

# Tool implementations
async def compile_solidity(code: str, filename: str = "Contract.sol") -> dict[str, Any]:
    """Compile Solidity source code."""
    print(f"Compiling Solidity: {filename}")
    
    try:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.sol', delete=False) as f:
            f.write(code)
            temp_file = f.name
        
        temp_dir = os.path.dirname(temp_file)
        cmd = [
            'solc',
            '--allow-paths', f"{temp_dir},{NODE_MODULES_PATH}",
            '--base-path', temp_dir,
            '--include-path', NODE_MODULES_PATH,
            '--combined-json', 'abi,bin,metadata',
            temp_file
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        os.unlink(temp_file)
        
        success = result.returncode == 0
        contracts = None
        errors = []
        warnings = []
        
        if success and result.stdout:
            try:
                output = json.loads(result.stdout)
                contracts = output.get('contracts', {})
            except json.JSONDecodeError as e:
                errors.append(f"Failed to parse compiler output: {str(e)}")
                success = False
        
        if result.stderr:
            lines = result.stderr.strip().split('\n')
            for line in lines:
                line = line.strip()
                if line:
                    if 'Error:' in line or 'error:' in line.lower():
                        errors.append(line)
                    elif 'Warning:' in line or 'warning:' in line.lower():
                        warnings.append(line)
        
        return {
            "success": success,
            "errors": errors,
            "warnings": warnings,
            "contracts": contracts,
            "filename": filename
        }
    
    except subprocess.TimeoutExpired:
        return {
            "success": False, 
            "errors": ["Compilation timeout"], 
            "warnings": [], 
            "contracts": None,
            "filename": filename
        }
    except Exception as e:
        return {
            "success": False, 
            "errors": [f"Compilation error: {str(e)}"], 
            "warnings": [], 
            "contracts": None,
            "filename": filename
        }

async def security_audit(code: str, filename: str = "Contract.sol") -> dict[str, Any]:
    """Run Slither security analysis."""
    print(f"Running security audit: {filename}")
    
    try:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.sol', delete=False) as f:
            f.write(code)
            temp_file = f.name
        
        temp_dir = os.path.dirname(temp_file)
        solc_args = f"--allow-paths {temp_dir},{NODE_MODULES_PATH} --base-path {temp_dir} --include-path {NODE_MODULES_PATH}"
        
        cmd = ['slither', '--json', '-', '--solc-args', solc_args, temp_file]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        
        os.unlink(temp_file)
        
        findings = []
        summary = {}
        success = False
        errors = []
        
        if result.stdout:
            try:
                output = json.loads(result.stdout)
                findings = output.get('results', {}).get('detectors', [])
                success = True
                
                severity_counts = {}
                for finding in findings:
                    impact = finding.get('impact', 'unknown')
                    severity_counts[impact] = severity_counts.get(impact, 0) + 1
                
                summary = {
                    "total_findings": len(findings),
                    "severity_breakdown": severity_counts
                }
                
            except json.JSONDecodeError as e:
                errors.append(f"Failed to parse Slither output: {str(e)}")
        
        if result.stderr and not success:
            errors.append(result.stderr.strip())
        
        if result.returncode == 0 and not success and not errors:
            success = True
            summary = {"total_findings": 0, "severity_breakdown": {}}
        
        return {
            "success": success,
            "findings": findings,
            "summary": summary,
            "errors": errors,
            "filename": filename
        }
    
    except subprocess.TimeoutExpired:
        return {
            "success": False, 
            "findings": [], 
            "summary": {}, 
            "errors": ["Analysis timeout"],
            "filename": filename
        }
    except Exception as e:
        return {
            "success": False, 
            "findings": [], 
            "summary": {}, 
            "errors": [f"Security audit error: {str(e)}"],
            "filename": filename
        }

async def compile_and_audit(code: str, filename: str = "Contract.sol") -> dict[str, Any]:
    """Compile and then audit Solidity code."""
    print(f"Running compile and audit workflow: {filename}")
    
    # Step 1: Compile
    compile_result = await compile_solidity(code, filename)
    
    if not compile_result["success"]:
        return {
            "workflow": "compile_and_audit",
            "compile_step": compile_result,
            "audit_step": {"skipped": True, "reason": "Compilation failed"},
            "overall_success": False,
            "filename": filename
        }
    
    # Step 2: Audit
    audit_result = await security_audit(code, filename)
    
    return {
        "workflow": "compile_and_audit", 
        "compile_step": compile_result,
        "audit_step": audit_result,
        "overall_success": compile_result["success"] and audit_result["success"],
        "filename": filename
    }

if __name__ == "__main__":
    print(f"Starting Solidity MCP Server on port {port}")
    print(f"SSE endpoint: http://0.0.0.0:{port}/sse")
    uvicorn.run(app, host="0.0.0.0", port=port)
