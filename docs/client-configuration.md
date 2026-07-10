# MCP client configuration reference

For a local editable install, point your MCP client at the virtualenv console
script so it always uses this checkout:

```json
{
  "mcpServers": {
    "google-finance": {
      "command": "/absolute/path/to/google-finance-mcp/.venv/bin/google-finance-mcp",
      "args": []
    }
  }
}
```

For a globally installed wheel or package, the shorter command is enough in
terminal-launched clients:

```json
{
  "mcpServers": {
    "google-finance": {
      "command": "google-finance-mcp",
      "args": []
    }
  }
}
```

Desktop apps may not inherit your shell `PATH`. If a client cannot find
`google-finance-mcp`, use the absolute path to the installed command instead.
