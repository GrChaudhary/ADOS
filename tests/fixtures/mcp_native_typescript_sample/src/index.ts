// Fixture mirroring the real-world shape found in
// github.com/spences10/mcp-sqlite-tools: a `tmcp`-based MCP server using
// TypeScript generics on the constructor call, which a naive
// `"McpServer("` substring check does not match.
import { McpServer } from 'tmcp';

export class Server {
	private server: McpServer<any>;

	constructor() {
		this.server = new McpServer<any>({ name: 'sample', version: '0.0.1' });
	}
}
