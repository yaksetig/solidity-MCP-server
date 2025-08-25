import os
import subprocess
import tempfile
import json
from typing import Any
import base64
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

# Async queue for server-sent events
notifications_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

# MCP Protocol endpoints
@app.get("/")
async def root():
    """Return server information and tool definitions."""
    return {
        "protocolVersion": "2024-11-05",
        "capabilities": {
            "tools": {
                "listChanged": True
            }
        },
        "serverInfo": {
            "name": "solidity-mcp",
            "version": "1.0.0"
        },
        "tools": TOOLS_SCHEMA,
    }


@app.get("/sse")
async def sse_stream():
    """Stream asynchronous notifications via Server-Sent Events."""

    async def event_generator():
        yield ": ready\n\n"
        while True:
            try:
                message = await asyncio.wait_for(
                    notifications_queue.get(), timeout=15
                )
                yield f"data: {json.dumps(message)}\n\n"
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"

    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
    }

    return StreamingResponse(
        event_generator(), media_type="text/event-stream", headers=headers
    )

@app.post("/")
async def handle_mcp_request(request: Request):
    """Handle MCP JSON-RPC requests"""
    try:
        body = await request.json()
        method = body.get("method")
        params = body.get("params", {})
        request_id = body.get("id")
        
        print(f"Received MCP request: {method} with ID: {request_id}")

        if method == "initialize":
            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "tools": {
                            "listChanged": True
                        }
                    },
                    "serverInfo": {
                        "name": "solidity-mcp",
                        "version": "1.0.0"
                    },
                    "tools": TOOLS_SCHEMA,
                }
            }
            print("Sending initialize response")
            return response
        
        elif method == "tools/list":
            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "tools": TOOLS_SCHEMA
                }
            }
            print(f"Sending tools/list response with {len(TOOLS_SCHEMA)} tools")
            return response
        
        elif method == "notifications/initialized":
            # This is a notification, no response needed
            print("Received initialized notification")
            return {"jsonrpc": "2.0"}
        
        elif method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments", {})
            
            print(f"Tool call: {tool_name} with args: {arguments}")
            
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
                        "message": f"Method not found: {tool_name}"
                    }
                }

            await notifications_queue.put(
                {
                    "jsonrpc": "2.0",
                    "method": "tools/call/result",
                    "params": {
                        "name": tool_name,
                        "id": request_id,
                        "success": result.get("success"),
                    },
                }
            )

            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2)
                        }
                    ]
                }
            }
        
        else:
            print(f"Unknown MCP method: {method} with params: {params}")
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32601,
                    "message": f"Method not found: {method}"
                }
            }
    
    except Exception as e:
        print(f"Error handling request: {str(e)}")
        return {
            "jsonrpc": "2.0",
            "id": body.get("id") if 'body' in locals() else None,
            "error": {
                "code": -32603,
                "message": f"Internal error: {str(e)}"
            }
        }

# Tool implementations
async def compile_solidity(code: str, filename: str = "Contract.sol") -> dict[str, Any]:
    """Compile Solidity source code."""
    try:
        # Create temporary file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.sol', delete=False) as f:
            f.write(code)
            temp_file = f.name
        
        # Run solc compilation with Node modules path for imports
        temp_dir = os.path.dirname(temp_file)
        result = subprocess.run([
            'solc',
            '--allow-paths', f"{temp_dir},{NODE_MODULES_PATH}",
            '--base-path', temp_dir,
            '--include-path', NODE_MODULES_PATH,
            '--combined-json', 'abi,bin,metadata',
            temp_file
        ], capture_output=True, text=True, timeout=30)
        
        # Clean up temp file
        os.unlink(temp_file)
        
        success = result.returncode == 0
        contracts = None
        errors = []
        warnings = []
        
        if success and result.stdout:
            try:
                output = json.loads(result.stdout)
                contracts = output.get('contracts', {})
            except json.JSONDecodeError:
                errors.append("Failed to parse compilation output")
        
        # Parse stderr for errors and warnings
        if result.stderr:
            lines = result.stderr.strip().split('\n')
            for line in lines:
                if 'Error:' in line:
                    errors.append(line.strip())
                elif 'Warning:' in line:
                    warnings.append(line.strip())
        
        return {
            "success": success,
            "errors": errors,
            "warnings": warnings,
            "contracts": contracts,
            "filename": filename
        }
    
    except subprocess.TimeoutExpired:
        return {"success": False, "errors": ["Compilation timeout"], "warnings": [], "contracts": None}
    except Exception as e:
        return {"success": False, "errors": [str(e)], "warnings": [], "contracts": None}

async def security_audit(code: str, filename: str = "Contract.sol") -> dict[str, Any]:
    """Run Slither security analysis on Solidity code."""
    try:
        # Create temporary file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.sol', delete=False) as f:
            f.write(code)
            temp_file = f.name
        
        # Run Slither analysis with solc import paths
        temp_dir = os.path.dirname(temp_file)
        solc_args = (
            f"--allow-paths {temp_dir},{NODE_MODULES_PATH} "
            f"--base-path {temp_dir} "
            f"--include-path {NODE_MODULES_PATH}"
        )
        result = subprocess.run([
            'slither', '--json', '-', '--solc-args', solc_args, temp_file
        ], capture_output=True, text=True, timeout=60)
        
        # Clean up temp file
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
                
                # Generate summary
                severity_counts = {}
                for finding in findings:
                    impact = finding.get('impact', 'unknown')
                    severity_counts[impact] = severity_counts.get(impact, 0) + 1
                
                summary = {
                    "total_findings": len(findings),
                    "severity_breakdown": severity_counts
                }
            except json.JSONDecodeError:
                errors.append("Failed to parse Slither output")
        
        if result.stderr and not success:
            errors.append(result.stderr.strip())
        
        return {
            "success": success or result.returncode == 0,
            "findings": findings,
            "summary": summary,
            "errors": errors,
            "filename": filename
        }
    
    except subprocess.TimeoutExpired:
        return {"success": False, "findings": [], "summary": {}, "errors": ["Analysis timeout"]}
    except Exception as e:
        return {"success": False, "findings": [], "summary": {}, "errors": [str(e)]}

async def compile_and_audit(code: str, filename: str = "Contract.sol") -> dict[str, Any]:
    """Compile Solidity code and then run security audit."""
    # Step 1: Compile
    compile_result = await compile_solidity(code, filename)
    
    if not compile_result["success"]:
        return {
            "workflow": "compile_and_audit",
            "compile_step": compile_result,
            "audit_step": {"skipped": "Compilation failed"},
            "overall_success": False
        }
    
    # Step 2: Audit
    audit_result = await security_audit(code, filename)
    
    return {
        "workflow": "compile_and_audit", 
        "compile_step": compile_result,
        "audit_step": audit_result,
        "overall_success": compile_result["success"] and audit_result["success"]
    }

if __name__ == "__main__":
    print(f"Starting Solidity MCP server on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
