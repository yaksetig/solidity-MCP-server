import os
import subprocess
import tempfile
import json
from typing import Any
import base64
from mcp.server.fastmcp import FastMCP

# Get port from Railway's environment variable
port = int(os.environ.get("PORT", 8080))

# Initialize Solidity MCP server with SSE transport
APP_DIR = os.path.dirname(os.path.abspath(__file__))
NODE_MODULES_PATH = os.path.join(APP_DIR, "node_modules")

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


@mcp.tool(
    description="Compile Circom code and return generated artifacts"
)
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


@mcp.tool(
    description="Run circomspect security analysis on Circom code"
)
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
