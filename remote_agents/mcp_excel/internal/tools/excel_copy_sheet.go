package tools

import (
	"context"
	"fmt"
	"html"

	z "github.com/Oudwins/zog"
	"github.com/mark3labs/mcp-go/mcp"
	"github.com/mark3labs/mcp-go/server"
	excel "github.com/negokaz/excel-mcp-server/internal/excel"
	imcp "github.com/negokaz/excel-mcp-server/internal/mcp"
)

type ExcelCopySheetArguments struct {
	FileAbsolutePath string `zog:"fileAbsolutePath"`
	SrcSheetName     string `zog:"srcSheetName"`
	DstSheetName     string `zog:"dstSheetName"`
}

var excelCopySheetArgumentsSchema = z.Struct(z.Shape{
	"fileAbsolutePath": z.String().Required(),
	"srcSheetName":     z.String().Required(),
	"dstSheetName":     z.String().Required(),
})

func AddExcelCopySheetTool(server *server.MCPServer) {
	server.AddTool(mcp.NewTool("excel_copy_sheet",
		mcp.WithDescription("Copy existing sheet to a new sheet"),
		mcp.WithString("fileAbsolutePath",
			mcp.Required(),
			mcp.Description("Absolute path to the Excel file"),
		),
		mcp.WithString("srcSheetName",
			mcp.Required(),
			mcp.Description("Source sheet name in the Excel file"),
		),
		mcp.WithString("dstSheetName",
			mcp.Required(),
			mcp.Description("Sheet name to be copied"),
		),
	), handleCopySheet)
}

func handleCopySheet(ctx context.Context, request mcp.CallToolRequest) (*mcp.CallToolResult, error) {
	args := ExcelCopySheetArguments{}
	if issues := excelCopySheetArgumentsSchema.Parse(request.Params.Arguments, &args); len(issues) != 0 {
		return imcp.NewToolResultZogIssueMap(issues), nil
	}
	return copySheet(args.FileAbsolutePath, args.SrcSheetName, args.DstSheetName)
}

func copySheet(fileAbsolutePath string, srcSheetName string, dstSheetName string) (*mcp.CallToolResult, error) {
	workbook, release, err := excel.OpenFile(fileAbsolutePath)
	if err != nil {
		return nil, err
	}
	defer release()

	srcSheet, err := workbook.FindSheet(srcSheetName)
	if err != nil {
		return imcp.NewToolResultInvalidArgumentError(err.Error()), nil
	}
	defer srcSheet.Release()
	srcSheetName, err = srcSheet.Name()
	if err != nil {
		return nil, err
	}

	if err := workbook.CopySheet(srcSheetName, dstSheetName); err != nil {
		return nil, err
	}
	if err := workbook.Save(); err != nil {
		return nil, err
	}

	result := "# Notice\n"
	result += fmt.Sprintf("backend: %s\n", workbook.GetBackendName())
	result += fmt.Sprintf("Sheet [%s] copied to [%s].\n", html.EscapeString(srcSheetName), html.EscapeString(dstSheetName))
	return mcp.NewToolResultText(result), nil
}
