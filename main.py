import os
import subprocess
import tempfile
import json
from typing import Any
from mcp.server.fastmcp import FastMCP

# Get port from Railway's environment variable
port = int(os.environ.get("PORT", 8080))

# Initialize Solidity MCP server with SSE transport
mcp = FastMCP("solidity-mcp", host="0.0.0.0", port=port)

@mcp.tool(
    description="Compile Solidity code and return compilation results"
)
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
        
        # Run solc compilation
        result = subprocess.run([
            'solc', '--combined-json', 'abi,bin,metadata', temp_file
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

@mcp.tool(
    description="Run Slither security analysis on Solidity code"
)
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
        
        # Run Slither analysis
        result = subprocess.run([
            'slither', '--json', '-', temp_file
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

@mcp.tool(
    description="Complete workflow: compile Solidity code then run security audit"
)
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
    mcp.run(transport='sse')
