#!/usr/bin/env node

import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import {
  CallToolRequestSchema,
  ErrorCode,
  ListToolsRequestSchema,
  McpError,
} from '@modelcontextprotocol/sdk/types.js';
import { spawn } from 'child_process';
import { promises as fs } from 'fs';
import path from 'path';
import os from 'os';

class SolidityMCPServer {
  constructor() {
    this.server = new Server(
      {
        name: 'solidity-compiler-auditor',
        version: '1.0.0',
      },
      {
        capabilities: {
          tools: {},
        },
      }
    );

    this.setupToolHandlers();
  }

  setupToolHandlers() {
    this.server.setRequestHandler(ListToolsRequestSchema, async () => {
      return {
        tools: [
          {
            name: 'compile_solidity',
            description: 'Compile Solidity code from text input',
            inputSchema: {
              type: 'object',
              properties: {
                code: {
                  type: 'string',
                  description: 'The Solidity source code as text',
                },
                filename: {
                  type: 'string',
                  description: 'Contract filename (default: Contract.sol)',
                  default: 'Contract.sol',
                },
              },
              required: ['code'],
            },
          },
          {
            name: 'security_audit',
            description: 'Run Slither security analysis on Solidity code from text input',
            inputSchema: {
              type: 'object',
              properties: {
                code: {
                  type: 'string',
                  description: 'The Solidity source code as text',
                },
                filename: {
                  type: 'string',
                  description: 'Contract filename (default: Contract.sol)',
                  default: 'Contract.sol',
                },
              },
              required: ['code'],
            },
          },
          {
            name: 'compile_and_audit',
            description: 'Complete workflow: compile then audit Solidity code',
            inputSchema: {
              type: 'object',
              properties: {
                code: {
                  type: 'string',
                  description: 'The Solidity source code as text',
                },
                filename: {
                  type: 'string',
                  description: 'Contract filename (default: Contract.sol)',
                  default: 'Contract.sol',
                },
              },
              required: ['code'],
            },
          },
        ],
      };
    });

    this.server.setRequestHandler(CallToolRequestSchema, async (request) => {
      const { name, arguments: args } = request.params;

      try {
        if (name === 'compile_solidity') {
          return await this.compileSolidity(args);
        } else if (name === 'security_audit') {
          return await this.runSecurityAudit(args);
        } else if (name === 'compile_and_audit') {
          return await this.compileAndAudit(args);
        } else {
          throw new McpError(
            ErrorCode.MethodNotFound,
            `Unknown tool: ${name}`
          );
        }
      } catch (error) {
        throw new McpError(
          ErrorCode.InternalError,
          `Error executing ${name}: ${error.message}`
        );
      }
    });
  }

  async createTempFile(filename, code) {
    const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), 'solidity-mcp-'));
    const filePath = path.join(tempDir, filename);
    await fs.writeFile(filePath, code, 'utf8');
    return { tempDir, filePath };
  }

  async cleanupTempDir(tempDir) {
    try {
      await fs.rm(tempDir, { recursive: true, force: true });
    } catch (error) {
      // Ignore cleanup errors
    }
  }

  async runCommand(command, args, options = {}) {
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

  async compileSolidity(args) {
    const { code, filename = 'Contract.sol' } = args;
    const { tempDir, filePath } = await this.createTempFile(filename, code);
    
    try {
      const { stdout, stderr, exitCode } = await this.runCommand('solc', [
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
      
      return {
        content: [
          {
            type: 'text',
            text: JSON.stringify({
              success,
              errors,
              warnings,
              contracts,
              raw_output: stdout
            }, null, 2),
          },
        ],
      };
    } finally {
      await this.cleanupTempDir(tempDir);
    }
  }

  async runSecurityAudit(args) {
    const { code, filename = 'Contract.sol' } = args;
    const { tempDir, filePath } = await this.createTempFile(filename, code);
    
    try {
      const { stdout, stderr, exitCode } = await this.runCommand('slither', [
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
      
      return {
        content: [
          {
            type: 'text',
            text: JSON.stringify({
              success: success || exitCode === 0,
              findings,
              summary,
              errors,
              raw_output: stdout
            }, null, 2),
          },
        ],
      };
    } finally {
      await this.cleanupTempDir(tempDir);
    }
  }

  async compileAndAudit(args) {
    const { code, filename = 'Contract.sol' } = args;
    
    // Step 1: Compile
    const compileResult = await this.compileSolidity({ code, filename });
    const compileData = JSON.parse(compileResult.content[0].text);
    
    if (!compileData.success) {
      return {
        content: [
          {
            type: 'text',
            text: JSON.stringify({
              workflow: 'compile_and_audit',
              compile_step: compileData,
              audit_step: { skipped: 'Compilation failed' },
              overall_success: false
            }, null, 2),
          },
        ],
      };
    }
    
    // Step 2: Audit
    const auditResult = await this.runSecurityAudit({ code, filename });
    const auditData = JSON.parse(auditResult.content[0].text);
    
    return {
      content: [
        {
          type: 'text',
          text: JSON.stringify({
            workflow: 'compile_and_audit',
            compile_step: compileData,
            audit_step: auditData,
            overall_success: compileData.success && auditData.success
          }, null, 2),
        },
      ],
    };
  }

  async run() {
    const transport = new StdioServerTransport();
    await this.server.connect(transport);
    console.error('Solidity MCP server running on stdio');
  }
}

const server = new SolidityMCPServer();
server.run().catch(console.error);
