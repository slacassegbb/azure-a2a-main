# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is an Excel MCP (Model Context Protocol) Server that enables AI assistants to interact with Microsoft Excel files. It provides a bridge between AI models and Excel spreadsheets for programmatic data manipulation.

## Development Commands

### Build and Development
```bash
npm run build     # Build Go binaries + compile TypeScript
npm run watch     # Watch TypeScript files for changes
npm run debug     # Debug with MCP inspector
```

### Testing
```bash
go test ./...                           # Run all Go tests
go test ./internal/tools -v             # Run specific package tests
go test -run TestReadSheetData ./internal/tools  # Run specific test
```

### Linting and Formatting
```bash
go fmt ./...      # Format Go code
go vet ./...      # Vet Go code for issues
```

## Architecture

### Core Components

**Dual Backend Architecture**: The server supports two Excel backends:
- **Windows**: OLE automation for live Excel interaction (`excel_ole.go`)  
- **Cross-platform**: Excelize library for file operations (`excel_excelize.go`)

**Key Interfaces**:
- `ExcelInterface` in `internal/excel/excel.go` - Unified Excel operations API
- `Tool` interface in `internal/tools/` - MCP tool implementations

**Entry Points**:
- `cmd/excel-mcp-server/main.go` - Go binary entry point
- `launcher/launcher.ts` - Cross-platform launcher that selects appropriate binary

### Tool System

MCP tools are implemented in `internal/tools/`:
- `excel_describe_sheets` - List worksheets and metadata
- `excel_read_sheet` - Read sheet data with pagination
- `excel_write_to_sheet` - Write data to sheets
- `excel_create_table` - Create Excel tables
- `excel_copy_sheet` - Copy sheets between workbooks
- `excel_screen_capture` - Windows-only screenshot functionality

### Pagination System

Large datasets are handled through configurable pagination:
- Default limit: 4000 cells
- Configurable via `EXCEL_MCP_PAGING_CELLS_LIMIT` environment variable
- Implemented in `internal/excel/pagination.go`

## File Structure

```
cmd/excel-mcp-server/     # Main application entry point
internal/
  excel/                  # Excel abstraction layer
  server/                 # MCP server implementation  
  tools/                  # MCP tool implementations
launcher/                 # TypeScript launcher
memory-bank/              # Development context and progress
```

## Build System

Uses GoReleaser (`.goreleaser.yaml`) to create cross-platform binaries:
- Windows: amd64, 386, arm64
- macOS: amd64, arm64  
- Linux: amd64, 386, arm64

TypeScript launcher is compiled to `dist/launcher.js` and published to NPM.

## Platform Differences

**Windows-specific features**:
- Live Excel interaction via OLE automation
- Screen capture capabilities
- Requires Excel to be installed

**Cross-platform features**:
- File-based Excel operations only
- No live editing capabilities
- Works with xlsx, xlsm, xltx, xltm formats

## Configuration

Environment variables:
- `EXCEL_MCP_PAGING_CELLS_LIMIT` - Maximum cells per page (default: 4000)

## Dependencies

**Go**: Requires Go 1.23.0+ with Go 1.24.0 toolchain
**Node.js**: Requires Node.js 20.x+ for TypeScript compilation
**Key packages**: 
- `github.com/mark3labs/mcp-go` - MCP framework
- `github.com/xuri/excelize/v2` - Excel file operations
- `github.com/go-ole/go-ole` - Windows OLE automation