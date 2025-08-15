import express from 'express';
import cors from 'cors';
import { spawn } from 'child_process';
import { promises as fs } from 'fs';
import path from 'path';
import os from 'os';

const app = express();
const port = process.env.PORT || 3000;

// Middleware
app.use(cors());
app.use(express.json({ limit: '10mb' }));

// Helper functions
async function createTempFile(filename, code) {
  const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), 'solidity-'));
  const filePath = path.join(tempDir, filename);
  await fs.writeFile(filePath, code, 'utf8');
  return { tempDir, filePath };
}

async function cleanupTempDir(tempDir) {
  try {
    await fs.rm(tempDir, { recursive: true, force: true });
  } catch (error) {
    // Ignore cleanup errors
  }
}

function runCommand(command, args, options = {}) {
  return new Promise((resolve) => {
    const process = spawn(command, args, options);
    
    let stdout = '';
    let stderr = '';
    
    process.stdout.on('data', (data) => {
      stdout += data.toString();
    });
    
    process.stderr.on('data', (data) => {
      stderr += data.toString();
    });
    
    process.on('close', (code) => {
      resolve({ stdout, stderr, exitCode: code });
    });

    process.on('error', (error) => {
      resolve({ stdout: '', stderr: error.message, exitCode: 1 });
    });
  });
}

// Routes
app.get('/health', (req, res) => {
  res.json({ 
    status: 'ok', 
    timestamp: new Date().toISOString(),
    endpoints: ['/compile', '/audit', '/compile-and-audit']
  });
});

app.post('/compile', async (req, res) => {
  try {
    const { code, filename = 'Contract.sol' } = req.body;
    
    if (!code) {
      return res.status(400).json({ error: 'Code is required' });
    }

    const { tempDir, filePath } = await createTempFile(filename, code);
    
    try {
      const { stdout, stderr, exitCode } = await runCommand('solc', [
        '--combined-json', 'abi,bin,metadata',
        filePath
      ], { cwd: tempDir });
      
      const success = exitCode === 0;
      let contracts = null;
      let errors = [];
      let warnings = [];
      
      if (success && stdout) {
        try {
          const output = JSON.parse(stdout);
          contracts = output.contracts;
        } catch (e) {
          errors.push('Failed to parse compilation output');
        }
      }
      
      if (stderr) {
        const lines = stderr.split('\n').filter(line => line.trim());
        lines.forEach(line => {
          if (line.includes('Error:')) {
            errors.push(line.trim());
          } else if (line.includes('Warning:')) {
            warnings.push(line.trim());
          }
        });
      }
      
      res.json({
        success,
        errors,
        warnings,
        contracts,
        filename
      });
    } finally {
      await cleanupTempDir(tempDir);
    }
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

app.post('/audit', async (req, res) => {
  try {
    const { code, filename = 'Contract.sol' } = req.body;
    
    if (!code) {
      return res.status(400).json({ error: 'Code is required' });
    }

    const { tempDir, filePath } = await createTempFile(filename, code);
    
    try {
      const { stdout, stderr, exitCode } = await runCommand('slither', [
        '--json', '-',
        filePath
      ], { cwd: tempDir });
      
      let findings = [];
      let summary = {};
      let success = false;
      let errors = [];
      
      if (stdout) {
        try {
          const output = JSON.parse(stdout);
          findings = output.results?.detectors || [];
          success = true;
          
          // Generate summary
          const severityCounts = {};
          findings.forEach(finding => {
            const impact = finding.impact || 'unknown';
            severityCounts[impact] = (severityCounts[impact] || 0) + 1;
          });
          
          summary = {
            total_findings: findings.length,
            severity_breakdown: severityCounts,
          };
        } catch (e) {
          errors.push('Failed to parse Slither output');
        }
      }
      
      if (stderr && !success) {
        errors.push(stderr.trim());
      }
      
      res.json({
        success: success || exitCode === 0,
        findings,
        summary,
        errors,
        filename
      });
    } finally {
      await cleanupTempDir(tempDir);
    }
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

app.post('/compile-and-audit', async (req, res) => {
  try {
    const { code, filename = 'Contract.sol' } = req.body;
    
    if (!code) {
      return res.status(400).json({ error: 'Code is required' });
    }

    // Step 1: Compile
    const compileResponse = await fetch(`http://localhost:${port}/compile`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code, filename })
    });
    const compileData = await compileResponse.json();
    
    if (!compileData.success) {
      return res.json({
        workflow: 'compile_and_audit',
        compile_step: compileData,
        audit_step: { skipped: 'Compilation failed' },
        overall_success: false
      });
    }
    
    // Step 2: Audit
    const auditResponse = await fetch(`http://localhost:${port}/audit`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code, filename })
    });
    const auditData = await auditResponse.json();
    
    res.json({
      workflow: 'compile_and_audit',
      compile_step: compileData,
      audit_step: auditData,
      overall_success: compileData.success && auditData.success
    });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

// Start server
app.listen(port, '0.0.0.0', () => {
  console.log(`🚀 Simple Solidity Server running on port ${port}`);
  console.log(`🏥 Health: http://localhost:${port}/health`);
  console.log(`🔧 Compile: POST http://localhost:${port}/compile`);
  console.log(`🔍 Audit: POST http://localhost:${port}/audit`);
  console.log(`⚡ Both: POST http://localhost:${port}/compile-and-audit`);
});

// Handle graceful shutdown
process.on('SIGTERM', () => {
  console.log('Received SIGTERM, shutting down gracefully');
  process.exit(0);
});

process.on('SIGINT', () => {
  console.log('Received SIGINT, shutting down gracefully');
  process.exit(0);
});
