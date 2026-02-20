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

type ExcelReadSheetArguments struct {
	FileAbsolutePath string `zog:"fileAbsolutePath"`
	SheetName        string `zog:"sheetName"`
	Range            string `zog:"range"`
	ShowFormula      bool   `zog:"showFormula"`
	ShowStyle        bool   `zog:"showStyle"`
}

var excelReadSheetArgumentsSchema = z.Struct(z.Shape{
	"fileAbsolutePath": z.String().Test(AbsolutePathTest()).Required(),
	"sheetName":        z.String().Required(),
	"range":            z.String(),
	"showFormula":      z.Bool().Default(false),
	"showStyle":        z.Bool().Default(false),
})

func AddExcelReadSheetTool(server *server.MCPServer) {
	server.AddTool(mcp.NewTool("excel_read_sheet",
		mcp.WithDescription("Read values from Excel sheet with pagination."),
		mcp.WithString("fileAbsolutePath",
			mcp.Required(),
			mcp.Description("Absolute path to the Excel file"),
		),
		mcp.WithString("sheetName",
			mcp.Required(),
			mcp.Description("Sheet name in the Excel file"),
		),
		mcp.WithString("range",
			mcp.Description("Range of cells to read in the Excel sheet (e.g., \"A1:C10\"). [default: first paging range]"),
		),
		mcp.WithBoolean("showFormula",
			mcp.Description("Show formula instead of value"),
		),
		mcp.WithBoolean("showStyle",
			mcp.Description("Show style information for cells"),
		),
	), handleReadSheet)
}

func handleReadSheet(ctx context.Context, request mcp.CallToolRequest) (*mcp.CallToolResult, error) {
	args := ExcelReadSheetArguments{}
	if issues := excelReadSheetArgumentsSchema.Parse(request.Params.Arguments, &args); len(issues) != 0 {
		return imcp.NewToolResultZogIssueMap(issues), nil
	}
	localPath, cleanup, err := ResolveFilePath(args.FileAbsolutePath)
	if err != nil {
		return nil, err
	}
	defer cleanup()
	return readSheet(localPath, args.SheetName, args.Range, args.ShowFormula, args.ShowStyle)
}

func readSheet(fileAbsolutePath string, sheetName string, valueRange string, showFormula bool, showStyle bool) (*mcp.CallToolResult, error) {
	config, issues := LoadConfig()
	if issues != nil {
		return imcp.NewToolResultZogIssueMap(issues), nil
	}

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

	// ページング戦略の初期化
	strategy, err := worksheet.GetPagingStrategy(config.EXCEL_MCP_PAGING_CELLS_LIMIT)
	if err != nil {
		return nil, err
	}
	pagingService := excel.NewPagingRangeService(strategy)

	// 利用可能な範囲を取得
	allRanges := pagingService.GetPagingRanges()
	if len(allRanges) == 0 {
		return imcp.NewToolResultInvalidArgumentError("no range available to read"), nil
	}

	// 現在の範囲を決定
	currentRange := valueRange
	if currentRange == "" && len(allRanges) > 0 {
		currentRange = allRanges[0]
	}

	// Find next paging range if current range matches a paging range
	nextRange := pagingService.FindNextRange(allRanges, currentRange)
	// Validate the current range against the used range
	usedRange, err := worksheet.GetDimention()
	if err != nil {
		return nil, err
	}
	if err := validateRangeWithinUsedRange(currentRange, usedRange); err != nil {
		return imcp.NewToolResultInvalidArgumentError(err.Error()), nil
	}

	// 範囲を解析
	startCol, startRow, endCol, endRow, err := excel.ParseRange(currentRange)
	if err != nil {
		return nil, err
	}

	// HTMLテーブルの生成
	var table *string
	if showStyle {
		if showFormula {
			table, err = CreateHTMLTableOfFormulaWithStyle(worksheet, startCol, startRow, endCol, endRow)
		} else {
			table, err = CreateHTMLTableOfValuesWithStyle(worksheet, startCol, startRow, endCol, endRow)
		}
	} else {
		if showFormula {
			table, err = CreateHTMLTableOfFormula(worksheet, startCol, startRow, endCol, endRow)
		} else {
			table, err = CreateHTMLTableOfValues(worksheet, startCol, startRow, endCol, endRow)
		}
	}
	if err != nil {
		return nil, err
	}

	result := "<h2>Read Sheet</h2>\n"
	result += *table + "\n"
	result += "<h2>Metadata</h2>\n"
	result += "<ul>\n"
	result += fmt.Sprintf("<li>backend: %s</li>\n", workbook.GetBackendName())
	result += fmt.Sprintf("<li>sheet name: %s</li>\n", html.EscapeString(sheetName))
	result += fmt.Sprintf("<li>read range: %s</li>\n", currentRange)
	result += "</ul>\n"
	result += "<h2>Notice</h2>\n"
	if nextRange != "" {
		result += "<p>This sheet has more ranges.</p>\n"
		result += "<p>To read the next range, you should specify 'range' argument as follows.</p>\n"
		result += fmt.Sprintf("<code>{ \"range\": \"%s\" }</code>\n", nextRange)
	} else {
		result += "<p>This is the last range or no more ranges available.</p>\n"
	}
	return mcp.NewToolResultText(result), nil
}

func validateRangeWithinUsedRange(targetRange, usedRange string) error {
	// Parse target range
	targetStartCol, targetStartRow, targetEndCol, targetEndRow, err := excel.ParseRange(targetRange)
	if err != nil {
		return fmt.Errorf("failed to parse target range: %w", err)
	}

	// Parse used range
	usedStartCol, usedStartRow, usedEndCol, usedEndRow, err := excel.ParseRange(usedRange)
	if err != nil {
		return fmt.Errorf("failed to parse used range: %w", err)
	}

	// Check if target range is within used range
	if targetStartCol < usedStartCol || targetStartRow < usedStartRow ||
		targetEndCol > usedEndCol || targetEndRow > usedEndRow {
		return fmt.Errorf("range is outside of used range: %s is not within %s", targetRange, usedRange)
	}

	return nil
}
