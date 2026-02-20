package tools

import (
	"context"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"

	z "github.com/Oudwins/zog"
	"github.com/mark3labs/mcp-go/mcp"
	"github.com/mark3labs/mcp-go/server"
	imcp "github.com/negokaz/excel-mcp-server/internal/mcp"
)

type ExcelOpenFromURLArguments struct {
	Url      string `zog:"url"`
	Filename string `zog:"filename"`
}

var excelOpenFromURLArgumentsSchema = z.Struct(z.Shape{
	"url":      z.String().Required(),
	"filename": z.String(),
})

func AddExcelOpenFromURLTool(server *server.MCPServer) {
	server.AddTool(mcp.NewTool("excel_open_from_url",
		mcp.WithDescription("Download an Excel file from a URL (e.g. Azure Blob Storage) to a local path for editing. Use this FIRST when editing an existing spreadsheet from a URL, then use write/format tools on the returned path."),
		mcp.WithString("url",
			mcp.Required(),
			mcp.Description("HTTP/HTTPS URL to the Excel file (including SAS tokens if needed)"),
		),
		mcp.WithString("filename",
			mcp.Description("Optional local filename to save as (default: derived from URL)"),
		),
	), handleOpenFromURL)
}

func handleOpenFromURL(ctx context.Context, request mcp.CallToolRequest) (*mcp.CallToolResult, error) {
	args := ExcelOpenFromURLArguments{}
	issues := excelOpenFromURLArgumentsSchema.Parse(request.Params.Arguments, &args)
	if len(issues) != 0 {
		return imcp.NewToolResultZogIssueMap(issues), nil
	}

	if !strings.HasPrefix(args.Url, "http://") && !strings.HasPrefix(args.Url, "https://") {
		return imcp.NewToolResultInvalidArgumentError("url must be an HTTP/HTTPS URL"), nil
	}

	// Determine filename
	urlPath := strings.SplitN(args.Url, "?", 2)[0]
	var safeName string
	if args.Filename != "" {
		safeName = filepath.Base(args.Filename)
		if !strings.HasSuffix(safeName, ".xlsx") {
			safeName += ".xlsx"
		}
	} else {
		safeName = filepath.Base(urlPath)
		if safeName == "" || safeName == "." || safeName == "/" {
			safeName = "spreadsheet.xlsx"
		}
		if !strings.HasSuffix(safeName, ".xlsx") {
			safeName += ".xlsx"
		}
	}

	downloadDir := "/tmp/xlsx_downloads"
	if err := os.MkdirAll(downloadDir, 0755); err != nil {
		return nil, fmt.Errorf("failed to create download directory: %w", err)
	}
	localPath := filepath.Join(downloadDir, safeName)

	// Download file
	resp, err := http.Get(args.Url)
	if err != nil {
		return imcp.NewToolResultInvalidArgumentError(fmt.Sprintf("failed to download file: %v", err)), nil
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return imcp.NewToolResultInvalidArgumentError(fmt.Sprintf("failed to download file: HTTP %d", resp.StatusCode)), nil
	}

	outFile, err := os.Create(localPath)
	if err != nil {
		return nil, fmt.Errorf("failed to create local file: %w", err)
	}
	defer outFile.Close()

	written, err := io.Copy(outFile, resp.Body)
	if err != nil {
		return nil, fmt.Errorf("failed to write downloaded file: %w", err)
	}

	sizeKB := float64(written) / 1024.0
	text := fmt.Sprintf(
		"File downloaded to %s (%.1f KB). Use this path with excel_write_to_sheet, excel_format_range, excel_create_table, etc. The file will be available for download at /download/%s when done.",
		localPath, sizeKB, safeName,
	)
	return mcp.NewToolResultText(text), nil
}
