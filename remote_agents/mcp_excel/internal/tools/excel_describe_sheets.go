package tools

import (
	"context"
	"encoding/json"

	z "github.com/Oudwins/zog"
	"github.com/mark3labs/mcp-go/mcp"
	"github.com/mark3labs/mcp-go/server"
	"github.com/negokaz/excel-mcp-server/internal/excel"
	imcp "github.com/negokaz/excel-mcp-server/internal/mcp"
)

type ExcelDescribeSheetsArguments struct {
	FileAbsolutePath string `zog:"fileAbsolutePath"`
}

var excelDescribeSheetsArgumentsSchema = z.Struct(z.Shape{
	"fileAbsolutePath": z.String().Test(AbsolutePathTest()).Required(),
})

func AddExcelDescribeSheetsTool(server *server.MCPServer) {
	server.AddTool(mcp.NewTool("excel_describe_sheets",
		mcp.WithDescription("List all sheet information of specified Excel file"),
		mcp.WithString("fileAbsolutePath",
			mcp.Required(),
			mcp.Description("Absolute path to the Excel file"),
		),
	), handleDescribeSheets)
}

func handleDescribeSheets(ctx context.Context, request mcp.CallToolRequest) (*mcp.CallToolResult, error) {
	args := ExcelDescribeSheetsArguments{}
	issues := excelDescribeSheetsArgumentsSchema.Parse(request.Params.Arguments, &args)
	if len(issues) != 0 {
		return imcp.NewToolResultZogIssueMap(issues), nil
	}
	return describeSheets(args.FileAbsolutePath)
}

type Response struct {
	Backend string      `json:"backend"`
	Sheets  []Worksheet `json:"sheets"`
}
type Worksheet struct {
	Name         string       `json:"name"`
	UsedRange    string       `json:"usedRange"`
	Tables       []Table      `json:"tables"`
	PivotTables  []PivotTable `json:"pivotTables"`
	PagingRanges []string     `json:"pagingRanges"`
}

type Table struct {
	Name  string `json:"name"`
	Range string `json:"range"`
}

type PivotTable struct {
	Name  string `json:"name"`
	Range string `json:"range"`
}

func describeSheets(fileAbsolutePath string) (*mcp.CallToolResult, error) {
	config, issues := LoadConfig()
	if issues != nil {
		return imcp.NewToolResultZogIssueMap(issues), nil
	}
	workbook, release, err := excel.OpenFile(fileAbsolutePath)
	defer release()
	if err != nil {
		return nil, err
	}

	sheetList, err := workbook.GetSheets()
	if err != nil {
		return nil, err
	}
	worksheets := make([]Worksheet, len(sheetList))
	for i, sheet := range sheetList {
		defer sheet.Release()
		name, err := sheet.Name()
		if err != nil {
			return nil, err
		}
		usedRange, err := sheet.GetDimention()
		if err != nil {
			return nil, err
		}
		tables, err := sheet.GetTables()
		if err != nil {
			return nil, err
		}
		tableList := make([]Table, len(tables))
		for i, table := range tables {
			tableList[i] = Table{
				Name:  table.Name,
				Range: table.Range,
			}
		}
		pivotTables, err := sheet.GetPivotTables()
		if err != nil {
			return nil, err
		}
		pivotTableList := make([]PivotTable, len(pivotTables))
		for i, pivotTable := range pivotTables {
			pivotTableList[i] = PivotTable{
				Name:  pivotTable.Name,
				Range: pivotTable.Range,
			}
		}
		var pagingRanges []string
		strategy, err := sheet.GetPagingStrategy(config.EXCEL_MCP_PAGING_CELLS_LIMIT)
		if err == nil {
			pagingService := excel.NewPagingRangeService(strategy)
			pagingRanges = pagingService.GetPagingRanges()
		}
		worksheets[i] = Worksheet{
			Name:         name,
			UsedRange:    usedRange,
			Tables:       tableList,
			PivotTables:  pivotTableList,
			PagingRanges: pagingRanges,
		}
	}
	response := Response{
		Backend: workbook.GetBackendName(),
		Sheets:  worksheets,
	}
	jsonBytes, err := json.MarshalIndent(response, "", "  ")
	if err != nil {
		return nil, err
	}

	return mcp.NewToolResultText(string(jsonBytes)), nil
}
