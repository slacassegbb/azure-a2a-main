package tools

import (
	"crypto/md5"
	"fmt"
	"html"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"slices"
	"strconv"
	"strings"

	"github.com/goccy/go-yaml"
	"github.com/xuri/excelize/v2"

	"github.com/negokaz/excel-mcp-server/internal/excel"

	z "github.com/Oudwins/zog"
)

type StyleRegistry struct {
	// Border styles
	borderStyles   map[string]string // styleID -> YAML string
	borderHashToID map[string]string // styleHash -> styleID
	borderCounter  int

	// Font styles
	fontStyles   map[string]string // styleID -> YAML string
	fontHashToID map[string]string // styleHash -> styleID
	fontCounter  int

	// Fill styles
	fillStyles   map[string]string // styleID -> YAML string
	fillHashToID map[string]string // styleHash -> styleID
	fillCounter  int

	// Number format styles
	numFmtStyles   map[string]string // styleID -> NumFmt
	numFmtHashToID map[string]string // styleHash -> styleID
	numFmtCounter  int

	// Decimal places styles
	decimalStyles   map[string]string // styleID -> YAML string
	decimalHashToID map[string]string // styleHash -> styleID
	decimalCounter  int
}

func NewStyleRegistry() *StyleRegistry {
	return &StyleRegistry{
		borderStyles:    make(map[string]string),
		borderHashToID:  make(map[string]string),
		borderCounter:   0,
		fontStyles:      make(map[string]string),
		fontHashToID:    make(map[string]string),
		fontCounter:     0,
		fillStyles:      make(map[string]string),
		fillHashToID:    make(map[string]string),
		fillCounter:     0,
		numFmtStyles:    make(map[string]string),
		numFmtHashToID:  make(map[string]string),
		numFmtCounter:   0,
		decimalStyles:   make(map[string]string),
		decimalHashToID: make(map[string]string),
		decimalCounter:  0,
	}
}

func (sr *StyleRegistry) RegisterStyle(cellStyle *excel.CellStyle) []string {
	if cellStyle == nil || sr.isEmptyStyle(cellStyle) {
		return []string{}
	}

	var styleIDs []string

	// Register border style
	if len(cellStyle.Border) > 0 {
		if borderID := sr.RegisterBorderStyle(cellStyle.Border); borderID != "" {
			styleIDs = append(styleIDs, borderID)
		}
	}

	// Register font style
	if cellStyle.Font != nil {
		if fontID := sr.RegisterFontStyle(cellStyle.Font); fontID != "" {
			styleIDs = append(styleIDs, fontID)
		}
	}

	// Register fill style
	if cellStyle.Fill != nil && cellStyle.Fill.Type != "" {
		if fillID := sr.RegisterFillStyle(cellStyle.Fill); fillID != "" {
			styleIDs = append(styleIDs, fillID)
		}
	}

	// Register number format style
	if cellStyle.NumFmt != nil && *cellStyle.NumFmt != "" {
		if numFmtID := sr.RegisterNumFmtStyle(*cellStyle.NumFmt); numFmtID != "" {
			styleIDs = append(styleIDs, numFmtID)
		}
	}

	// Register decimal places style
	if cellStyle.DecimalPlaces != nil && *cellStyle.DecimalPlaces != 0 {
		if decimalID := sr.RegisterDecimalStyle(*cellStyle.DecimalPlaces); decimalID != "" {
			styleIDs = append(styleIDs, decimalID)
		}
	}

	return styleIDs
}

func (sr *StyleRegistry) isEmptyStyle(style *excel.CellStyle) bool {
	if len(style.Border) > 0 || style.Font != nil || (style.NumFmt != nil && *style.NumFmt != "") || (style.DecimalPlaces != nil && *style.DecimalPlaces != 0) {
		return false
	}
	if style.Fill != nil && style.Fill.Type != "" {
		return false
	}
	return true
}

// calculateYamlHash calculates a hash for a YAML string
func calculateYamlHash(yaml string) string {
	if yaml == "" {
		return ""
	}
	hash := md5.Sum([]byte(yaml))
	return fmt.Sprintf("%x", hash)[:8]
}

// Individual style element registration methods
func (sr *StyleRegistry) RegisterBorderStyle(borders []excel.Border) string {
	if len(borders) == 0 {
		return ""
	}

	yamlStr := convertToYAMLFlow(borders)
	if yamlStr == "" {
		return ""
	}

	styleHash := calculateYamlHash(yamlStr)
	if styleHash == "" {
		return ""
	}

	if existingID, exists := sr.borderHashToID[styleHash]; exists {
		return existingID
	}

	sr.borderCounter++
	styleID := fmt.Sprintf("b%d", sr.borderCounter)
	sr.borderStyles[styleID] = yamlStr
	sr.borderHashToID[styleHash] = styleID

	return styleID
}

func (sr *StyleRegistry) RegisterFontStyle(font *excel.FontStyle) string {
	if font == nil {
		return ""
	}

	yamlStr := convertToYAMLFlow(font)
	if yamlStr == "" {
		return ""
	}

	styleHash := calculateYamlHash(yamlStr)
	if styleHash == "" {
		return ""
	}

	if existingID, exists := sr.fontHashToID[styleHash]; exists {
		return existingID
	}

	sr.fontCounter++
	styleID := fmt.Sprintf("f%d", sr.fontCounter)
	sr.fontStyles[styleID] = yamlStr
	sr.fontHashToID[styleHash] = styleID

	return styleID
}

func (sr *StyleRegistry) RegisterFillStyle(fill *excel.FillStyle) string {
	if fill == nil || fill.Type == "" {
		return ""
	}

	yamlStr := convertToYAMLFlow(fill)
	if yamlStr == "" {
		return ""
	}

	styleHash := calculateYamlHash(yamlStr)
	if styleHash == "" {
		return ""
	}

	if existingID, exists := sr.fillHashToID[styleHash]; exists {
		return existingID
	}

	sr.fillCounter++
	styleID := fmt.Sprintf("l%d", sr.fillCounter)
	sr.fillStyles[styleID] = yamlStr
	sr.fillHashToID[styleHash] = styleID

	return styleID
}

func (sr *StyleRegistry) RegisterNumFmtStyle(numFmt string) string {
	if numFmt == "" {
		return ""
	}

	styleHash := calculateYamlHash(numFmt)
	if styleHash == "" {
		return ""
	}

	if existingID, exists := sr.numFmtHashToID[styleHash]; exists {
		return existingID
	}

	sr.numFmtCounter++
	styleID := fmt.Sprintf("n%d", sr.numFmtCounter)
	sr.numFmtStyles[styleID] = numFmt
	sr.numFmtHashToID[styleHash] = styleID

	return styleID
}

func (sr *StyleRegistry) RegisterDecimalStyle(decimal int) string {
	if decimal == 0 {
		return ""
	}

	yamlStr := convertToYAMLFlow(decimal)
	if yamlStr == "" {
		return ""
	}

	styleHash := calculateYamlHash(yamlStr)
	if styleHash == "" {
		return ""
	}

	if existingID, exists := sr.decimalHashToID[styleHash]; exists {
		return existingID
	}

	sr.decimalCounter++
	styleID := fmt.Sprintf("d%d", sr.decimalCounter)
	sr.decimalStyles[styleID] = yamlStr
	sr.decimalHashToID[styleHash] = styleID

	return styleID
}

func (sr *StyleRegistry) GenerateStyleDefinitions() string {
	totalCount := len(sr.borderStyles) + len(sr.fontStyles) + len(sr.fillStyles) + len(sr.numFmtStyles) + len(sr.decimalStyles)
	if totalCount == 0 {
		return ""
	}

	var result strings.Builder
	result.WriteString("<h2>Style Definitions</h2>\n")
	result.WriteString("<div class=\"style-definitions\">\n")

	// Generate border style definitions
	result.WriteString(sr.generateStyleDefTag(sr.borderStyles, "border"))

	// Generate font style definitions
	result.WriteString(sr.generateStyleDefTag(sr.fontStyles, "font"))

	// Generate fill style definitions
	result.WriteString(sr.generateStyleDefTag(sr.fillStyles, "fill"))

	// Generate number format style definitions
	result.WriteString(sr.generateStyleDefTag(sr.numFmtStyles, "numFmt"))

	// Generate decimal places style definitions
	result.WriteString(sr.generateStyleDefTag(sr.decimalStyles, "decimalPlaces"))

	result.WriteString("</div>\n\n")
	return result.String()
}

func (sr *StyleRegistry) generateStyleDefTag(styles map[string]string, styleLabel string) string {
	if len(styles) == 0 {
		return ""
	}

	var styleIDs []string
	for styleID := range styles {
		styleIDs = append(styleIDs, styleID)
	}
	sortStyleIDs(styleIDs)

	var result strings.Builder
	for _, styleID := range styleIDs {
		yamlStr := styles[styleID]
		if yamlStr != "" {
			result.WriteString(fmt.Sprintf("<code class=\"style language-yaml\" id=\"%s\">%s: %s</code>\n", styleID, styleLabel, html.EscapeString(yamlStr)))
		}
	}
	return result.String()
}

func sortStyleIDs(styleIDs []string) {
	slices.SortFunc(styleIDs, func(a, b string) int {
		// styleID must have number suffix after prefix
		ai, _ := strconv.Atoi(a[1:])
		bi, _ := strconv.Atoi(b[1:])
		return ai - bi
	})
}

// Common function to convert any value to YAML flow format
func convertToYAMLFlow(value any) string {
	if value == nil {
		return ""
	}
	yamlBytes, err := yaml.MarshalWithOptions(value, yaml.Flow(true), yaml.OmitEmpty())
	if err != nil {
		return ""
	}
	yamlStr := strings.TrimSpace(strings.ReplaceAll(string(yamlBytes), "\"", ""))
	return yamlStr
}

func CreateHTMLTableOfValues(worksheet excel.Worksheet, startCol int, startRow int, endCol int, endRow int) (*string, error) {
	return createHTMLTable(startCol, startRow, endCol, endRow, func(cellRange string) (string, error) {
		return worksheet.GetValue(cellRange)
	})
}

func CreateHTMLTableOfFormula(worksheet excel.Worksheet, startCol int, startRow int, endCol int, endRow int) (*string, error) {
	return createHTMLTable(startCol, startRow, endCol, endRow, func(cellRange string) (string, error) {
		return worksheet.GetFormula(cellRange)
	})
}

// CreateHTMLTable creates a table data in HTML format
func createHTMLTable(startCol int, startRow int, endCol int, endRow int, extractor func(cellRange string) (string, error)) (*string, error) {
	return createHTMLTableWithStyle(startCol, startRow, endCol, endRow, extractor, nil)
}

func CreateHTMLTableOfValuesWithStyle(worksheet excel.Worksheet, startCol int, startRow int, endCol int, endRow int) (*string, error) {
	return createHTMLTableWithStyle(startCol, startRow, endCol, endRow,
		func(cellRange string) (string, error) {
			return worksheet.GetValue(cellRange)
		},
		func(cellRange string) (*excel.CellStyle, error) {
			return worksheet.GetCellStyle(cellRange)
		})
}

func CreateHTMLTableOfFormulaWithStyle(worksheet excel.Worksheet, startCol int, startRow int, endCol int, endRow int) (*string, error) {
	return createHTMLTableWithStyle(startCol, startRow, endCol, endRow,
		func(cellRange string) (string, error) {
			return worksheet.GetFormula(cellRange)
		},
		func(cellRange string) (*excel.CellStyle, error) {
			return worksheet.GetCellStyle(cellRange)
		})
}

func createHTMLTableWithStyle(startCol int, startRow int, endCol int, endRow int, extractor func(cellRange string) (string, error), styleExtractor func(cellRange string) (*excel.CellStyle, error)) (*string, error) {
	registry := NewStyleRegistry()

	// データとスタイルを収集
	var result strings.Builder
	result.WriteString("<table>\n<tr><th></th>")

	// 列アドレスの出力
	for col := startCol; col <= endCol; col++ {
		name, _ := excelize.ColumnNumberToName(col)
		result.WriteString(fmt.Sprintf("<th>%s</th>", name))
	}
	result.WriteString("</tr>\n")

	// データの出力とスタイル登録
	for row := startRow; row <= endRow; row++ {
		result.WriteString("<tr>")
		result.WriteString(fmt.Sprintf("<th>%d</th>", row))

		for col := startCol; col <= endCol; col++ {
			axis, _ := excelize.CoordinatesToCellName(col, row)
			value, _ := extractor(axis)

			var tdTag string
			if styleExtractor != nil {
				cellStyle, err := styleExtractor(axis)
				if err == nil && cellStyle != nil {
					styleIDs := registry.RegisterStyle(cellStyle)
					if len(styleIDs) > 0 {
						tdTag = fmt.Sprintf("<td style-ref=\"%s\">", strings.Join(styleIDs, " "))
					} else {
						tdTag = "<td>"
					}
				} else {
					tdTag = "<td>"
				}
			} else {
				tdTag = "<td>"
			}

			result.WriteString(fmt.Sprintf("%s%s</td>", tdTag, strings.ReplaceAll(html.EscapeString(value), "\n", "<br>")))
		}
		result.WriteString("</tr>\n")
	}

	result.WriteString("</table>")

	// スタイル定義とテーブルを結合
	var finalResult strings.Builder
	styleDefinitions := registry.GenerateStyleDefinitions()
	if styleDefinitions != "" {
		finalResult.WriteString(styleDefinitions)
	}

	finalResult.WriteString("<h2>Sheet Data</h2>\n")
	finalResult.WriteString(result.String())

	finalResultStr := finalResult.String()
	return &finalResultStr, nil
}

func AbsolutePathTest() z.Test[*string] {
	return z.Test[*string]{
		Func: func(path *string, ctx z.Ctx) {
			if strings.HasPrefix(*path, "http://") || strings.HasPrefix(*path, "https://") {
				return // URLs are allowed
			}
			if !filepath.IsAbs(*path) {
				ctx.AddIssue(ctx.Issue().SetMessage(fmt.Sprintf("Path '%s' is not absolute", *path)))
			}
		},
	}
}

// ResolveFilePath downloads a URL to a temp file if needed. Returns (localPath, cleanup func, error).
// The caller MUST call the cleanup function when done.
func ResolveFilePath(path string) (string, func(), error) {
	noop := func() {}
	if !strings.HasPrefix(path, "http://") && !strings.HasPrefix(path, "https://") {
		return path, noop, nil
	}

	// Guess extension from URL path (strip query params)
	urlPath := strings.SplitN(path, "?", 2)[0]
	ext := filepath.Ext(urlPath)
	if ext == "" {
		ext = ".xlsx"
	}

	tmpFile, err := os.CreateTemp("", "excel-mcp-*"+ext)
	if err != nil {
		return "", noop, fmt.Errorf("failed to create temp file: %w", err)
	}
	tmpPath := tmpFile.Name()
	cleanup := func() { os.Remove(tmpPath) }

	resp, err := http.Get(path)
	if err != nil {
		tmpFile.Close()
		cleanup()
		return "", noop, fmt.Errorf("failed to download file from URL: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		tmpFile.Close()
		cleanup()
		return "", noop, fmt.Errorf("failed to download file: HTTP %d", resp.StatusCode)
	}

	if _, err := io.Copy(tmpFile, resp.Body); err != nil {
		tmpFile.Close()
		cleanup()
		return "", noop, fmt.Errorf("failed to write downloaded file: %w", err)
	}
	tmpFile.Close()

	return tmpPath, cleanup, nil
}
