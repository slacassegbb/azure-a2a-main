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

type ExcelCreateTableArguments struct {
	FileAbsolutePath string `zog:"fileAbsolutePath"`
	SheetName        string `zog:"sheetName"`
	Range            string `zog:"range"`
	TableName        string `zog:"tableName"`
}

var excelCreateTableArgumentsSchema = z.Struct(z.Shape{
	"fileAbsolutePath": z.String().Test(AbsolutePathTest()).Required(),
	"sheetName":        z.String().Required(),
	"range":            z.String(),
	"tableName":        z.String().Required(),
})

func AddExcelCreateTableTool(server *server.MCPServer) {
	server.AddTool(mcp.NewTool("excel_create_table",
		mcp.WithDescription("Create a table in the Excel sheet"),
		mcp.WithString("fileAbsolutePath",
			mcp.Required(),
			mcp.Description("Absolute path to the Excel file"),
		),
		mcp.WithString("sheetName",
			mcp.Required(),
			mcp.Description("Sheet name where the table is created"),
		),
		mcp.WithString("range",
			mcp.Description("Range to be a table (e.g., \"A1:C10\")"),
		),
		mcp.WithString("tableName",
			mcp.Required(),
			mcp.Description("Table name to be created"),
		),
	), handleCreateTable)
}

func handleCreateTable(ctx context.Context, request mcp.CallToolRequest) (*mcp.CallToolResult, error) {
	args := ExcelCreateTableArguments{}
	if issues := excelCreateTableArgumentsSchema.Parse(request.Params.Arguments, &args); len(issues) != 0 {
		return imcp.NewToolResultZogIssueMap(issues), nil
	}
	return createTable(args.FileAbsolutePath, args.SheetName, args.Range, args.TableName)
}

func createTable(fileAbsolutePath string, sheetName string, tableRange string, tableName string) (*mcp.CallToolResult, error) {
	workbook, release, err := excel.OpenFile(fileAbsolutePath)
	if err != nil {
		return nil, err
	}
	defer release()

	worksheet, err := workbook.FindSheet(sheetName)
	if err != nil {
		return imcp.NewToolResultInvalidArgumentError(err.Error()), nil
	}
	defer worksheet.Release()
	if err := worksheet.AddTable(tableRange, tableName); err != nil {
		return nil, err
	}
	if err := workbook.Save(); err != nil {
		return nil, err
	}

	result := "# Notice\n"
	result += fmt.Sprintf("backend: %s\n", workbook.GetBackendName())
	result += fmt.Sprintf("Table [%s] created.\n", html.EscapeString(tableName))
	return mcp.NewToolResultText(result), nil
}
