import os
import subprocess
import tempfile
import json
from typing import Any
import base64
import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

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

# MCP Protocol endpoints
@app.get("/")
async def root():
    return {
        "jsonrpc": "2.0",
        "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": {}
            },
            "serverInfo": {
                "name": "solidity-mcp",
                "version": "1.0.0"
            }
        }
    }

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
                    }
                }
            }
            print(f"Sending initialize response: {response}")
            return response
        
        elif method == "tools/list":
            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "tools": [
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
                }
            }
            print(f"Sending tools/list response with {len(response['result']['tools'])} tools")
            return response
        
        elif method == "notifications/initialized":
            # This is a notification, no response needed
            print("Received initialized notification")
            return {"jsonrpc": "2.0"}
        
        elif method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments", {})
            
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
            elif tool_name == "compile_circom":
                result = await compile_circom(
                    arguments.get("code"),
                    arguments.get("filename", "circuit.circom")
                )
            elif tool_name == "audit_circom":
                result = await audit_circom(
                    arguments.get("code"),
                    arguments.get("filename", "circuit.circom")
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
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32601,
                    "message": f"Method not found: {method}"
                }
            }
    
    except Exception as e:
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
    """Compile Solidity source code.
    
    Args:
        code: The Solidity source code as text
        filename: Optional filename for the contract (default: Contract.sol)
    """
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
    """Run Slither security analysis on Solidity code.
    
    Args:
        code: The Solidity source code as text
        filename: Optional filename for the contract (default: Contract.sol)
    """
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

async def compile_circom(code: str, filename: str = "circuit.circom") -> dict[str, Any]:
    """Compile Circom source code using the circom compiler.

    Args:
        code: The Circom source code as text
        filename: Optional filename for the circuit (default: circuit.circom)
    """
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = os.path.join(tmpdir, filename)
            with open(source_path, "w") as f:
                f.write(code)

            result = subprocess.run([
                "circom",
                source_path,
                "--r1cs",
                "--wasm",
                "--json",
                "--sym",
                "--output",
                tmpdir,
            ], capture_output=True, text=True, timeout=60)

            success = result.returncode == 0
            errors: list[str] = []
            warnings: list[str] = []

            # Parse stderr for errors and warnings
            if result.stderr:
                for line in result.stderr.strip().split("\n"):
                    if "Error" in line:
                        errors.append(line.strip())
                    elif "Warning" in line:
                        warnings.append(line.strip())

            artifacts: dict[str, str] = {}
            if success:
                for root_dir, _, files in os.walk(tmpdir):
                    for file in files:
                        path = os.path.join(root_dir, file)
                        if path == source_path:
                            continue
                        with open(path, "rb") as af:
                            rel = os.path.relpath(path, tmpdir)
                            artifacts[rel] = base64.b64encode(af.read()).decode()

            return {
                "success": success,
                "errors": errors,
                "warnings": warnings,
                "artifacts": artifacts,
                "stdout": result.stdout,
                "filename": filename,
            }

    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "errors": ["Compilation timeout"],
            "warnings": [],
            "artifacts": {},
            "stdout": "",
        }
    except Exception as e:
        return {
            "success": False,
            "errors": [str(e)],
            "warnings": [],
            "artifacts": {},
            "stdout": "",
        }

async def audit_circom(code: str, filename: str = "circuit.circom") -> dict[str, Any]:
    """Run circomspect security analysis on Circom code.

    Args:
        code: The Circom source code as text
        filename: Optional filename for the circuit (default: circuit.circom)
    """
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".circom", delete=False) as f:
            f.write(code)
            temp_file = f.name

        result = subprocess.run(
            ["circomspect", temp_file, "--format", "json"],
            capture_output=True,
            text=True,
            timeout=60,
        )

        os.unlink(temp_file)

        findings: list[Any] = []
        summary: dict[str, Any] = {}
        errors: list[str] = []
        success = False

        if result.stdout:
            try:
                output = json.loads(result.stdout)
                findings = output.get("findings", output.get("issues", []))
                severity_counts: dict[str, int] = {}
                for item in findings:
                    sev = item.get("severity", item.get("level", "unknown"))
                    severity_counts[sev] = severity_counts.get(sev, 0) + 1
                summary = {
                    "total_findings": len(findings),
                    "severity_breakdown": severity_counts,
                }
                success = True
            except json.JSONDecodeError:
                errors.append("Failed to parse circomspect output")

        if result.stderr and not success:
            errors.append(result.stderr.strip())

        return {
            "success": success or result.returncode == 0,
            "findings": findings,
            "summary": summary,
            "errors": errors,
            "filename": filename,
        }

    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "findings": [],
            "summary": {},
            "errors": ["Analysis timeout"],
        }
    except Exception as e:
        return {
            "success": False,
            "findings": [],
            "summary": {},
            "errors": [str(e)],
        }

async def compile_and_audit(code: str, filename: str = "Contract.sol") -> dict[str, Any]:
    """Compile Solidity code and then run security audit.
    
    Args:
        code: The Solidity source code as text
        filename: Optional filename for the contract (default: Contract.sol)
    """
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
