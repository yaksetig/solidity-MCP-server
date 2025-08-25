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

@app.get("/")
async def root():
    """Return server information and available endpoints."""
    return {
        "name": "Solidity MCP Server",
        "version": "1.0.0",
        "endpoints": {
            "mcp": "/mcp",
            "sse": "/sse",
            "health": "/health"
        },
        "description": "MCP server for Solidity compilation and security auditing"
    }

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "solidity-mcp"}

# SSE endpoint - support both GET and POST
@app.get("/sse")
@app.post("/sse")
async def sse_stream():
    """Stream asynchronous notifications via Server-Sent Events."""
    
    async def event_generator():
        yield "data: {\"type\": \"connection\", \"message\": \"SSE connection established\"}\n\n"
        
        while True:
            try:
                message = await asyncio.wait_for(
                    notifications_queue.get(), timeout=30
                )
                yield f"data: {json.dumps(message)}\n\n"
            except asyncio.TimeoutError:
                yield "data: {\"type\": \"keepalive\", \"timestamp\": \"" + str(asyncio.get_event_loop().time()) + "\"}\n\n"

    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "*",
    }

    return StreamingResponse(
        event_generator(), 
        media_type="text/plain", 
        headers=headers
    )

@app.post("/mcp")
async def handle_mcp_request(request: Request):
    """Handle MCP JSON-RPC requests at /mcp endpoint"""
    try:
        body = await request.json()
        method = body.get("method")
        params = body.get("params", {})
        request_id = body.get("id")
        
        print(f"MCP Request - Method: {method}, ID: {request_id}")
        print(f"MCP Params: {params}")

        if method == "initialize":
            # Use the client's protocol version if provided, otherwise use our default
            client_protocol_version = params.get("protocolVersion", "2024-11-05")
            
            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": client_protocol_version,
                    "capabilities": {
                        "tools": {
                            "listChanged": True
                        }
                    },
                    "serverInfo": {
                        "name": "solidity-mcp",
                        "version": "1.0.0"
                    },
                    "tools": TOOLS_SCHEMA
                }
            }
            print(f"Sending initialize response with protocol version: {client_protocol_version} and {len(TOOLS_SCHEMA)} tools")
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
            # This is a notification, no response needed for notifications
            print("Received initialized notification")
            return None
        
        elif method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments", {})
            
            print(f"Tool call: {tool_name}")
            print(f"Arguments: {arguments}")
            
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

                # Send notification
                notification = {
                    "jsonrpc": "2.0",
                    "method": "notifications/tool_result",
                    "params": {
                        "tool": tool_name,
                        "success": result.get("success", False),
                        "timestamp": asyncio.get_event_loop().time()
                    }
                }
                
                try:
                    notifications_queue.put_nowait(notification)
                except asyncio.QueueFull:
                    print("Notification queue full, skipping notification")

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
                
            except Exception as tool_error:
                print(f"Tool execution error: {str(tool_error)}")
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32603,
                        "message": f"Tool execution failed: {str(tool_error)}"
                    }
                }
        
        else:
            print(f"Unknown MCP method: {method}")
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32601,
                    "message": f"Method not found: {method}"
                }
            }
    
    except json.JSONDecodeError as e:
        print(f"JSON decode error: {str(e)}")
        return {
            "jsonrpc": "2.0",
            "id": None,
            "error": {
                "code": -32700,
                "message": "Parse error: Invalid JSON"
            }
        }
    except Exception as e:
        print(f"Unexpected error: {str(e)}")
        request_id = body.get("id") if 'body' in locals() else None
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": -32603,
                "message": f"Internal error: {str(e)}"
            }
        }

# Legacy endpoint for backward compatibility
@app.post("/")
async def handle_legacy_mcp_request(request: Request):
    """Legacy MCP endpoint - redirects to /mcp"""
    return await handle_mcp_request(request)

# Tool implementations
async def compile_solidity(code: str, filename: str = "Contract.sol") -> dict[str, Any]:
    """Compile Solidity source code."""
    print(f"Starting Solidity compilation for {filename}")
    
    try:
        # Create temporary file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.sol', delete=False) as f:
            f.write(code)
            temp_file = f.name
        
        print(f"Created temp file: {temp_file}")
        
        # Run solc compilation
        temp_dir = os.path.dirname(temp_file)
        cmd = [
            'solc',
            '--allow-paths', f"{temp_dir},{NODE_MODULES_PATH}",
            '--base-path', temp_dir,
            '--include-path', NODE_MODULES_PATH,
            '--combined-json', 'abi,bin,metadata',
            temp_file
        ]
        
        print(f"Running command: {' '.join(cmd)}")
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        print(f"Compilation result - Return code: {result.returncode}")
        print(f"Stdout: {result.stdout[:500]}...")
        print(f"Stderr: {result.stderr[:500]}...")
        
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
                print(f"Found {len(contracts)} contracts")
            except json.JSONDecodeError as e:
                print(f"JSON decode error: {e}")
                errors.append(f"Failed to parse compilation output: {str(e)}")
                success = False
        
        # Parse stderr for errors and warnings
        if result.stderr:
            lines = result.stderr.strip().split('\n')
            for line in lines:
                line = line.strip()
                if line:
                    if 'Error:' in line or 'error:' in line.lower():
                        errors.append(line)
                    elif 'Warning:' in line or 'warning:' in line.lower():
                        warnings.append(line)
                    elif line and not any(skip in line.lower() for skip in ['compiling', 'compiler version']):
                        # Treat other non-empty lines as potential errors
                        if not success:
                            errors.append(line)
        
        result_data = {
            "success": success,
            "errors": errors,
            "warnings": warnings,
            "contracts": contracts,
            "filename": filename,
            "solc_version": "detected" if success else "unknown"
        }
        
        print(f"Compilation completed - Success: {success}, Errors: {len(errors)}, Warnings: {len(warnings)}")
        return result_data
    
    except subprocess.TimeoutExpired:
        print("Compilation timeout")
        return {
            "success": False, 
            "errors": ["Compilation timeout (30s limit exceeded)"], 
            "warnings": [], 
            "contracts": None,
            "filename": filename
        }
    except Exception as e:
        print(f"Compilation exception: {str(e)}")
        return {
            "success": False, 
            "errors": [f"Compilation error: {str(e)}"], 
            "warnings": [], 
            "contracts": None,
            "filename": filename
        }

async def security_audit(code: str, filename: str = "Contract.sol") -> dict[str, Any]:
    """Run Slither security analysis on Solidity code."""
    print(f"Starting security audit for {filename}")
    
    try:
        # Create temporary file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.sol', delete=False) as f:
            f.write(code)
            temp_file = f.name
        
        print(f"Created temp file for audit: {temp_file}")
        
        # Run Slither analysis
        temp_dir = os.path.dirname(temp_file)
        solc_args = (
            f"--allow-paths {temp_dir},{NODE_MODULES_PATH} "
            f"--base-path {temp_dir} "
            f"--include-path {NODE_MODULES_PATH}"
        )
        
        cmd = ['slither', '--json', '-', '--solc-args', solc_args, temp_file]
        print(f"Running Slither: {' '.join(cmd)}")
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        
        print(f"Slither result - Return code: {result.returncode}")
        print(f"Stdout length: {len(result.stdout) if result.stdout else 0}")
        print(f"Stderr: {result.stderr[:500] if result.stderr else 'None'}...")
        
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
                
                print(f"Found {len(findings)} security findings")
                
                # Generate summary
                severity_counts = {}
                for finding in findings:
                    impact = finding.get('impact', 'unknown')
                    severity_counts[impact] = severity_counts.get(impact, 0) + 1
                
                summary = {
                    "total_findings": len(findings),
                    "severity_breakdown": severity_counts,
                    "analysis_completed": True
                }
                
            except json.JSONDecodeError as e:
                print(f"Failed to parse Slither JSON output: {e}")
                errors.append(f"Failed to parse Slither output: {str(e)}")
        
        # Handle stderr
        if result.stderr:
            stderr_lines = [line.strip() for line in result.stderr.strip().split('\n') if line.strip()]
            # Only treat as errors if analysis wasn't successful
            if not success:
                errors.extend(stderr_lines)
            else:
                # Log but don't treat as errors if we got successful JSON output
                print(f"Slither stderr (non-fatal): {result.stderr}")
        
        # If we got a 0 return code but no JSON, that might still be success with no findings
        if result.returncode == 0 and not success and not errors:
            success = True
            summary = {
                "total_findings": 0,
                "severity_breakdown": {},
                "analysis_completed": True
            }
        
        result_data = {
            "success": success,
            "findings": findings,
            "summary": summary,
            "errors": errors,
            "filename": filename
        }
        
        print(f"Security audit completed - Success: {success}, Findings: {len(findings)}, Errors: {len(errors)}")
        return result_data
    
    except subprocess.TimeoutExpired:
        print("Security audit timeout")
        return {
            "success": False, 
            "findings": [], 
            "summary": {}, 
            "errors": ["Security analysis timeout (60s limit exceeded)"],
            "filename": filename
        }
    except Exception as e:
        print(f"Security audit exception: {str(e)}")
        return {
            "success": False, 
            "findings": [], 
            "summary": {}, 
            "errors": [f"Security audit error: {str(e)}"],
            "filename": filename
        }

async def compile_and_audit(code: str, filename: str = "Contract.sol") -> dict[str, Any]:
    """Compile Solidity code and then run security audit."""
    print(f"Starting complete workflow (compile + audit) for {filename}")
    
    # Step 1: Compile
    print("Step 1: Compilation")
    compile_result = await compile_solidity(code, filename)
    
    if not compile_result["success"]:
        print("Compilation failed, skipping audit")
        return {
            "workflow": "compile_and_audit",
            "compile_step": compile_result,
            "audit_step": {
                "skipped": True,
                "reason": "Compilation failed",
                "success": False
            },
            "overall_success": False,
            "filename": filename
        }
    
    # Step 2: Audit
    print("Step 2: Security Audit")
    audit_result = await security_audit(code, filename)
    
    overall_success = compile_result["success"] and audit_result["success"]
    
    result = {
        "workflow": "compile_and_audit", 
        "compile_step": compile_result,
        "audit_step": audit_result,
        "overall_success": overall_success,
        "filename": filename,
        "summary": {
            "compilation": "passed" if compile_result["success"] else "failed",
            "security_audit": "completed" if audit_result["success"] else "failed",
            "total_warnings": len(compile_result.get("warnings", [])),
            "total_security_findings": len(audit_result.get("findings", []))
        }
    }
    
    print(f"Complete workflow finished - Overall success: {overall_success}")
    return result

if __name__ == "__main__":
    print(f"Starting Solidity MCP server on port {port}")
    print("Available endpoints:")
    print(f"  - Health check: http://0.0.0.0:{port}/health")
    print(f"  - MCP endpoint: http://0.0.0.0:{port}/mcp")
    print(f"  - SSE stream: http://0.0.0.0:{port}/sse")
    print(f"  - Legacy MCP: http://0.0.0.0:{port}/")
    uvicorn.run(app, host="0.0.0.0", port=port)
