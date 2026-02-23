package tools

import (
	"context"
	"fmt"
	"regexp"

	z "github.com/Oudwins/zog"
	"github.com/mark3labs/mcp-go/mcp"
	"github.com/mark3labs/mcp-go/server"
	"github.com/negokaz/excel-mcp-server/internal/excel"
	imcp "github.com/negokaz/excel-mcp-server/internal/mcp"
	"github.com/xuri/excelize/v2"
)

type ExcelFormatRangeArguments struct {
	FileAbsolutePath string               `zog:"fileAbsolutePath"`
	SheetName        string               `zog:"sheetName"`
	Range            string               `zog:"range"`
	Styles           [][]*excel.CellStyle `zog:"styles"`
}

var colorPattern, _ = regexp.Compile("^#[0-9A-Fa-f]{6}$")

var excelFormatRangeArgumentsSchema = z.Struct(z.Shape{
	"fileAbsolutePath": z.String().Test(AbsolutePathTest()).Required(),
	"sheetName":        z.String().Required(),
	"range":            z.String().Required(),
	"styles": z.Slice(z.Slice(
		z.Ptr(z.Struct(z.Shape{
			"border": z.Slice(z.Struct(z.Shape{
				"type":  z.StringLike[excel.BorderType]().OneOf(excel.BorderTypeValues()).Required(),
				"color": z.String().Match(colorPattern).Default("#000000"),
				"style": z.StringLike[excel.BorderStyle]().OneOf(excel.BorderStyleValues()).Default(excel.BorderStyleContinuous),
			})).Default([]excel.Border{}),
			"font": z.Ptr(z.Struct(z.Shape{
				"bold":      z.Ptr(z.Bool()),
				"italic":    z.Ptr(z.Bool()),
				"underline": z.Ptr(z.StringLike[excel.FontUnderline]().OneOf(excel.FontUnderlineValues())),
				"size":      z.Ptr(z.Int().GTE(1).LTE(409)),
				"strike":    z.Ptr(z.Bool()),
				"color":     z.Ptr(z.String().Match(colorPattern)),
				"vertAlign": z.Ptr(z.StringLike[excel.FontVertAlign]().OneOf(excel.FontVertAlignValues())),
			})),
			"fill": z.Ptr(z.Struct(z.Shape{
				"type":    z.StringLike[excel.FillType]().OneOf(excel.FillTypeValues()).Default(excel.FillTypePattern),
				"pattern": z.StringLike[excel.FillPattern]().OneOf(excel.FillPatternValues()).Default(excel.FillPatternSolid),
				"color":   z.Slice(z.String().Match(colorPattern)).Default([]string{}),
				"shading": z.Ptr(z.StringLike[excel.FillShading]().OneOf(excel.FillShadingValues())),
			})),
			"numFmt":        z.Ptr(z.String()),
			"decimalPlaces": z.Ptr(z.Int().GTE(0).LTE(30)),
		}),
		))).Required(),
})

func AddExcelFormatRangeTool(server *server.MCPServer) {
	server.AddTool(mcp.NewTool("excel_format_range",
		mcp.WithDescription("Format cells in the Excel sheet with style information"),
		mcp.WithString("fileAbsolutePath",
			mcp.Required(),
			mcp.Description("Absolute path to the Excel file"),
		),
		mcp.WithString("sheetName",
			mcp.Required(),
			mcp.Description("Sheet name in the Excel file"),
		),
		mcp.WithString("range",
			mcp.Required(),
			mcp.Description("Range of cells in the Excel sheet (e.g., \"A1:C3\")"),
		),
		mcp.WithArray("styles",
			mcp.Required(),
			mcp.Description("2D array of style objects for each cell. If a cell does not change style, use null. The number of items of the array must match the range size."),
			mcp.Items(map[string]any{
				"type": "array",
				"items": map[string]any{
					"anyOf": []any{
						map[string]any{
							"type":        "object",
							"description": "Style object for the cell",
							"properties": map[string]any{
								"border": map[string]any{
									"type": "array",
									"items": map[string]any{
										"type": "object",
										"properties": map[string]any{
											"type": map[string]any{
												"type": "string",
												"enum": excel.BorderTypeValues(),
											},
											"color": map[string]any{
												"type":    "string",
												"pattern": colorPattern.String(),
											},
											"style": map[string]any{
												"type": "string",
												"enum": excel.BorderStyleValues(),
											},
										},
										"required": []string{"type"},
									},
								},
								"font": map[string]any{
									"type": "object",
									"properties": map[string]any{
										"bold":   map[string]any{"type": "boolean"},
										"italic": map[string]any{"type": "boolean"},
										"underline": map[string]any{
											"type": "string",
											"enum": excel.FontUnderlineValues(),
										},
										"size": map[string]any{
											"type":    "number",
											"minimum": 1,
											"maximum": 409,
										},
										"strike": map[string]any{"type": "boolean"},
										"color": map[string]any{
											"type":    "string",
											"pattern": colorPattern.String(),
										},
										"vertAlign": map[string]any{
											"type": "string",
											"enum": excel.FontVertAlignValues(),
										},
									},
								},
								"fill": map[string]any{
									"type": "object",
									"properties": map[string]any{
										"type": map[string]any{
											"type": "string",
											"enum": []string{"gradient", "pattern"},
										},
										"pattern": map[string]any{
											"type": "string",
											"enum": excel.FillPatternValues(),
										},
										"color": map[string]any{
											"type": "array",
											"items": map[string]any{
												"type":    "string",
												"pattern": colorPattern.String(),
											},
										},
										"shading": map[string]any{
											"type": "string",
											"enum": excel.FillShadingValues(),
										},
									},
									"required": []string{"type", "pattern", "color"},
								},
								"numFmt": map[string]any{
									"type":        "string",
									"description": "Custom number format string",
								},
								"decimalPlaces": map[string]any{
									"type":    "integer",
									"minimum": 0,
									"maximum": 30,
								},
							},
						},
						map[string]any{
							"type":        "null",
							"description": "No style applied to this cell",
						},
					},
				},
			}),
		),
	), handleFormatRange)
}

func handleFormatRange(ctx context.Context, request mcp.CallToolRequest) (*mcp.CallToolResult, error) {
	args := ExcelFormatRangeArguments{}
	issues := excelFormatRangeArgumentsSchema.Parse(request.Params.Arguments, &args)
	if len(issues) != 0 {
		return imcp.NewToolResultZogIssueMap(issues), nil
	}
	return formatRange(args.FileAbsolutePath, args.SheetName, args.Range, args.Styles)
}

func formatRange(fileAbsolutePath string, sheetName string, rangeStr string, styles [][]*excel.CellStyle) (*mcp.CallToolResult, error) {
	workbook, closeFn, err := excel.OpenFile(fileAbsolutePath)
	if err != nil {
		return nil, err
	}
	defer closeFn()

	startCol, startRow, endCol, endRow, err := excel.ParseRange(rangeStr)
	if err != nil {
		return imcp.NewToolResultInvalidArgumentError(err.Error()), nil
	}

	// Check data consistency
	rangeRowSize := endRow - startRow + 1
	if len(styles) != rangeRowSize {
		return imcp.NewToolResultInvalidArgumentError(fmt.Sprintf("number of style rows (%d) does not match range size (%d)", len(styles), rangeRowSize)), nil
	}

	// Get worksheet
	worksheet, err := workbook.FindSheet(sheetName)
	if err != nil {
		return imcp.NewToolResultInvalidArgumentError(err.Error()), nil
	}
	defer worksheet.Release()

	// Apply styles to each cell
	for i, styleRow := range styles {
		rangeColumnSize := endCol - startCol + 1
		if len(styleRow) != rangeColumnSize {
			return imcp.NewToolResultInvalidArgumentError(fmt.Sprintf("number of style columns in row %d (%d) does not match range size (%d)", i, len(styleRow), rangeColumnSize)), nil
		}

		for j, style := range styleRow {
			cell, err := excelize.CoordinatesToCellName(startCol+j, startRow+i)
			if err != nil {
				return nil, err
			}
			if style != nil {
				if err := worksheet.SetCellStyle(cell, style); err != nil {
					return nil, fmt.Errorf("failed to set style for cell %s: %w", cell, err)
				}
			}
		}
	}

	if err := workbook.Save(); err != nil {
		return nil, err
	}

	// Create response HTML
	html := "<h2>Formatted Range</h2>\n"
	html += fmt.Sprintf("<p>Successfully applied styles to range %s in sheet %s</p>\n", rangeStr, sheetName)
	html += "<h2>Metadata</h2>\n"
	html += "<ul>\n"
	html += fmt.Sprintf("<li>backend: %s</li>\n", workbook.GetBackendName())
	html += fmt.Sprintf("<li>sheet name: %s</li>\n", sheetName)
	html += fmt.Sprintf("<li>formatted range: %s</li>\n", rangeStr)
	html += fmt.Sprintf("<li>cells processed: %d</li>\n", (endRow-startRow+1)*(endCol-startCol+1))
	html += "</ul>\n"
	html += "<h2>Notice</h2>\n"
	html += "<p>Cell styles applied successfully.</p>\n"

	return mcp.NewToolResultText(html), nil
}
