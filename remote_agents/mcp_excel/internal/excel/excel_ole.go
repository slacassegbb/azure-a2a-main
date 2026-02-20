package excel

import (
	"bufio"
	"bytes"
	"encoding/base64"
	"fmt"
	"io"
	"path/filepath"
	"regexp"
	"runtime"
	"strings"

	"github.com/go-ole/go-ole"
	"github.com/go-ole/go-ole/oleutil"
	"github.com/skanehira/clipboard-image"
)

type OleExcel struct {
	application *ole.IDispatch
	workbook    *ole.IDispatch
}

type OleWorksheet struct {
	excel     *OleExcel
	worksheet *ole.IDispatch
}

func NewExcelOle(absolutePath string) (*OleExcel, func(), error) {
	runtime.LockOSThread()
	ole.CoInitializeEx(0, ole.COINIT_APARTMENTTHREADED)

	unknown, err := oleutil.GetActiveObject("Excel.Application")
	if err != nil {
		return nil, func() {}, err
	}
	excel, err := unknown.QueryInterface(ole.IID_IDispatch)
	if err != nil {
		return nil, func() {}, err
	}
	oleutil.MustPutProperty(excel, "ScreenUpdating", false)
	oleutil.MustPutProperty(excel, "EnableEvents", false)
	workbooks := oleutil.MustGetProperty(excel, "Workbooks").ToIDispatch()
	c := oleutil.MustGetProperty(workbooks, "Count").Val
	for i := 1; i <= int(c); i++ {
		workbook := oleutil.MustGetProperty(workbooks, "Item", i).ToIDispatch()
		fullName := oleutil.MustGetProperty(workbook, "FullName").ToString()
		name := oleutil.MustGetProperty(workbook, "Name").ToString()
		if strings.HasPrefix(fullName, "https:") && name == filepath.Base(absolutePath) {
			// If a workbook is opened through a WOPI URL, its absolute file path cannot be retrieved.
			// If the absolutePath is not writable, it assumes that the workbook has opened by WOPI.
			if FileIsNotWritable(absolutePath) {
				return &OleExcel{application: excel, workbook: workbook}, func() {
					oleutil.MustPutProperty(excel, "EnableEvents", true)
					oleutil.MustPutProperty(excel, "ScreenUpdating", true)
					workbook.Release()
					workbooks.Release()
					excel.Release()
					ole.CoUninitialize()
					runtime.UnlockOSThread()
				}, nil
			} else {
				// This workbook might not be specified with the absolutePath
			}
		} else if normalizePath(fullName) == normalizePath(absolutePath) {
			return &OleExcel{application: excel, workbook: workbook}, func() {
				oleutil.MustPutProperty(excel, "EnableEvents", true)
				oleutil.MustPutProperty(excel, "ScreenUpdating", true)
				workbook.Release()
				workbooks.Release()
				excel.Release()
				ole.CoUninitialize()
				runtime.UnlockOSThread()
			}, nil
		}
	}
	return nil, func() {}, fmt.Errorf("workbook not found: %s", absolutePath)
}

func NewExcelOleWithNewObject(absolutePath string) (*OleExcel, func(), error) {
	runtime.LockOSThread()
	ole.CoInitializeEx(0, ole.COINIT_APARTMENTTHREADED)

	unknown, err := oleutil.CreateObject("Excel.Application")
	if err != nil {
		return nil, func() {}, err
	}
	excel, err := unknown.QueryInterface(ole.IID_IDispatch)
	if err != nil {
		return nil, func() {}, err
	}
	workbooks := oleutil.MustGetProperty(excel, "Workbooks").ToIDispatch()
	workbook, err := oleutil.CallMethod(workbooks, "Open", absolutePath)
	if err != nil {
		return nil, func() {}, err
	}
	w := workbook.ToIDispatch()
	return &OleExcel{application: excel, workbook: w}, func() {
		w.Release()
		workbooks.Release()
		excel.Release()
		oleutil.CallMethod(excel, "Close")
		ole.CoUninitialize()
		runtime.UnlockOSThread()
	}, nil
}

func (o *OleExcel) GetBackendName() string {
	return "ole"
}

func (o *OleExcel) GetSheets() ([]Worksheet, error) {
	worksheets := oleutil.MustGetProperty(o.workbook, "Worksheets").ToIDispatch()
	defer worksheets.Release()

	count := int(oleutil.MustGetProperty(worksheets, "Count").Val)
	worksheetList := make([]Worksheet, count)

	for i := 1; i <= count; i++ {
		worksheet := oleutil.MustGetProperty(worksheets, "Item", i).ToIDispatch()
		worksheetList[i-1] = &OleWorksheet{
			excel:     o,
			worksheet: worksheet,
		}
	}
	return worksheetList, nil
}

func (o *OleExcel) FindSheet(sheetName string) (Worksheet, error) {
	worksheets := oleutil.MustGetProperty(o.workbook, "Worksheets").ToIDispatch()
	defer worksheets.Release()

	count := int(oleutil.MustGetProperty(worksheets, "Count").Val)

	for i := 1; i <= count; i++ {
		worksheet := oleutil.MustGetProperty(worksheets, "Item", i).ToIDispatch()
		name := oleutil.MustGetProperty(worksheet, "Name").ToString()

		if name == sheetName {
			return &OleWorksheet{
				excel:     o,
				worksheet: worksheet,
			}, nil
		}
	}

	return nil, fmt.Errorf("sheet not found: %s", sheetName)
}

func (o *OleExcel) CreateNewSheet(sheetName string) error {
	activeWorksheet := oleutil.MustGetProperty(o.workbook, "ActiveSheet").ToIDispatch()
	defer activeWorksheet.Release()
	activeWorksheetIndex := oleutil.MustGetProperty(activeWorksheet, "Index").Val
	worksheets := oleutil.MustGetProperty(o.workbook, "Worksheets").ToIDispatch()
	defer worksheets.Release()

	_, err := oleutil.CallMethod(worksheets, "Add", nil, activeWorksheet)
	if err != nil {
		return err
	}

	worksheet := oleutil.MustGetProperty(worksheets, "Item", activeWorksheetIndex+1).ToIDispatch()
	defer worksheet.Release()

	_, err = oleutil.PutProperty(worksheet, "Name", sheetName)
	if err != nil {
		return err
	}

	return nil
}

func (o *OleExcel) CopySheet(srcSheetName string, dstSheetName string) error {
	worksheets := oleutil.MustGetProperty(o.workbook, "Worksheets").ToIDispatch()
	defer worksheets.Release()

	srcSheetVariant, err := oleutil.GetProperty(worksheets, "Item", srcSheetName)
	if err != nil {
		return fmt.Errorf("faild to get sheet: %w", err)
	}
	srcSheet := srcSheetVariant.ToIDispatch()
	defer srcSheet.Release()
	srcSheetIndex := oleutil.MustGetProperty(srcSheet, "Index").Val

	_, err = oleutil.CallMethod(srcSheet, "Copy", nil, srcSheet)
	if err != nil {
		return err
	}

	dstSheetVariant, err := oleutil.GetProperty(worksheets, "Item", srcSheetIndex+1)
	if err != nil {
		return fmt.Errorf("failed to get copied sheet: %w", err)
	}
	dstSheet := dstSheetVariant.ToIDispatch()
	defer dstSheet.Release()

	_, err = oleutil.PutProperty(dstSheet, "Name", dstSheetName)
	if err != nil {
		return err
	}

	return nil
}

func (o *OleExcel) Save() error {
	_, err := oleutil.CallMethod(o.workbook, "Save")
	if err != nil {
		return err
	}
	return nil
}

func (o *OleWorksheet) Release() {
	o.worksheet.Release()
}

func (o *OleWorksheet) Name() (string, error) {
	name := oleutil.MustGetProperty(o.worksheet, "Name").ToString()
	return name, nil
}

func (o *OleWorksheet) GetTables() ([]Table, error) {
	tables := oleutil.MustGetProperty(o.worksheet, "ListObjects").ToIDispatch()
	defer tables.Release()
	count := int(oleutil.MustGetProperty(tables, "Count").Val)
	tableList := make([]Table, count)
	for i := 1; i <= count; i++ {
		table := oleutil.MustGetProperty(tables, "Item", i).ToIDispatch()
		defer table.Release()
		name := oleutil.MustGetProperty(table, "Name").ToString()
		defer table.Release()
		tableRange := oleutil.MustGetProperty(table, "Range").ToIDispatch()
		defer tableRange.Release()
		tableList[i-1] = Table{
			Name:  name,
			Range: NormalizeRange(oleutil.MustGetProperty(tableRange, "Address").ToString()),
		}
	}
	return tableList, nil
}

func (o *OleWorksheet) GetPivotTables() ([]PivotTable, error) {
	pivotTables := oleutil.MustGetProperty(o.worksheet, "PivotTables").ToIDispatch()
	defer pivotTables.Release()
	count := int(oleutil.MustGetProperty(pivotTables, "Count").Val)
	pivotTableList := make([]PivotTable, count)
	for i := 1; i <= count; i++ {
		pivotTable := oleutil.MustGetProperty(pivotTables, "Item", i).ToIDispatch()
		defer pivotTable.Release()
		name := oleutil.MustGetProperty(pivotTable, "Name").ToString()
		pivotTableRange := oleutil.MustGetProperty(pivotTable, "TableRange1").ToIDispatch()
		defer pivotTableRange.Release()
		pivotTableList[i-1] = PivotTable{
			Name:  name,
			Range: NormalizeRange(oleutil.MustGetProperty(pivotTableRange, "Address").ToString()),
		}
	}
	return pivotTableList, nil
}

func (o *OleWorksheet) SetValue(cell string, value any) error {
	range_ := oleutil.MustGetProperty(o.worksheet, "Range", cell).ToIDispatch()
	defer range_.Release()
	_, err := oleutil.PutProperty(range_, "Value", value)
	return err
}

func (o *OleWorksheet) SetFormula(cell string, formula string) error {
	range_ := oleutil.MustGetProperty(o.worksheet, "Range", cell).ToIDispatch()
	defer range_.Release()
	_, err := oleutil.PutProperty(range_, "Formula", formula)
	return err
}

func (o *OleWorksheet) GetValue(cell string) (string, error) {
	range_ := oleutil.MustGetProperty(o.worksheet, "Range", cell).ToIDispatch()
	defer range_.Release()
	value := oleutil.MustGetProperty(range_, "Text").Value()
	switch v := value.(type) {
	case string:
		return v, nil
	case nil:
		return "", nil
	default: // Handle other types as needed
		return "", fmt.Errorf("unsupported type: %T", v)
	}
}

func (o *OleWorksheet) GetFormula(cell string) (string, error) {
	range_ := oleutil.MustGetProperty(o.worksheet, "Range", cell).ToIDispatch()
	defer range_.Release()
	formula := oleutil.MustGetProperty(range_, "Formula").ToString()
	return formula, nil
}

func (o *OleWorksheet) GetDimention() (string, error) {
	range_ := oleutil.MustGetProperty(o.worksheet, "UsedRange").ToIDispatch()
	defer range_.Release()
	dimension := oleutil.MustGetProperty(range_, "Address").ToString()
	return NormalizeRange(dimension), nil
}

func (o *OleWorksheet) GetPagingStrategy(pageSize int) (PagingStrategy, error) {
	return NewOlePagingStrategy(1000, o)
}

func (o *OleWorksheet) PrintArea() (string, error) {
	v, err := oleutil.GetProperty(o.worksheet, "PageSetup")
	if err != nil {
		return "", err
	}
	pageSetup := v.ToIDispatch()
	defer pageSetup.Release()

	printArea := oleutil.MustGetProperty(pageSetup, "PrintArea").ToString()
	return printArea, nil
}

func (o *OleWorksheet) HPageBreaks() ([]int, error) {
	v, err := oleutil.GetProperty(o.worksheet, "HPageBreaks")
	if err != nil {
		return nil, err
	}
	hPageBreaks := v.ToIDispatch()
	defer hPageBreaks.Release()

	count := int(oleutil.MustGetProperty(hPageBreaks, "Count").Val)
	pageBreaks := make([]int, count)
	for i := 1; i <= count; i++ {
		pageBreak := oleutil.MustGetProperty(hPageBreaks, "Item", i).ToIDispatch()
		defer pageBreak.Release()
		location := oleutil.MustGetProperty(pageBreak, "Location").ToIDispatch()
		defer location.Release()
		row := oleutil.MustGetProperty(location, "Row").Val
		pageBreaks[i-1] = int(row)
	}
	return pageBreaks, nil
}

func (o *OleWorksheet) CapturePicture(captureRange string) (string, error) {
	r := oleutil.MustGetProperty(o.worksheet, "Range", captureRange).ToIDispatch()
	defer r.Release()
	_, err := oleutil.CallMethod(
		r,
		"CopyPicture",
		int(1), // xlScreen (https://learn.microsoft.com/ja-jp/dotnet/api/microsoft.office.interop.excel.xlpictureappearance?view=excel-pia)
		int(2), // xlBitmap (https://learn.microsoft.com/ja-jp/dotnet/api/microsoft.office.interop.excel.xlcopypictureformat?view=excel-pia)
	)
	if err != nil {
		return "", err
	}
	// Read the image from the clipboard
	buf := new(bytes.Buffer)
	bufWriter := bufio.NewWriter(buf)
	clipboardReader, err := clipboard.ReadFromClipboard()
	if err != nil {
		return "", fmt.Errorf("failed to read from clipboard: %w", err)
	}
	if _, err := io.Copy(bufWriter, clipboardReader); err != nil {
		return "", fmt.Errorf("failed to copy clipboard data: %w", err)
	}
	if err := bufWriter.Flush(); err != nil {
		return "", fmt.Errorf("failed to flush buffer: %w", err)
	}
	return base64.StdEncoding.EncodeToString(buf.Bytes()), nil
}

func (o *OleWorksheet) AddTable(tableRange string, tableName string) error {
	tables := oleutil.MustGetProperty(o.worksheet, "ListObjects").ToIDispatch()
	defer tables.Release()

	// https://learn.microsoft.com/ja-jp/office/vba/api/excel.listobjects.add
	tableVar, err := oleutil.CallMethod(
		tables,
		"Add",
		int(1), // xlSrcRange (https://learn.microsoft.com/ja-jp/office/vba/api/excel.xllistobjectsourcetype)
		tableRange,
		nil,
		int(0), // xlYes (https://learn.microsoft.com/ja-jp/office/vba/api/excel.xlyesnoguess)
	)
	if err != nil {
		return err
	}
	table := tableVar.ToIDispatch()
	defer table.Release()
	_, err = oleutil.PutProperty(table, "Name", tableName)
	if err != nil {
		return err
	}
	return err
}

func (o *OleWorksheet) GetCellStyle(cell string) (*CellStyle, error) {
	rng := oleutil.MustGetProperty(o.worksheet, "Range", cell).ToIDispatch()
	defer rng.Release()

	style := &CellStyle{}

	// Get Font information
	normalStyle := oleutil.MustGetProperty(o.excel.workbook, "Styles", "Normal").ToIDispatch()
	defer normalStyle.Release()
	normalFont := oleutil.MustGetProperty(normalStyle, "Font").ToIDispatch()
	defer normalFont.Release()
	font := oleutil.MustGetProperty(rng, "Font").ToIDispatch()
	defer font.Release()

	normalFontSize := int(oleutil.MustGetProperty(normalFont, "Size").Value().(float64))
	normalFontBold := oleutil.MustGetProperty(normalFont, "Bold").Value().(bool)
	normalFontItalic := oleutil.MustGetProperty(normalFont, "Italic").Value().(bool)
	normalFontColor := oleutil.MustGetProperty(normalFont, "Color").Value().(float64)

	fontSize := int(oleutil.MustGetProperty(font, "Size").Value().(float64))
	fontBold := oleutil.MustGetProperty(font, "Bold").Value().(bool)
	fontItalic := oleutil.MustGetProperty(font, "Italic").Value().(bool)
	fontColor := oleutil.MustGetProperty(font, "Color").Value().(float64)

	if fontSize != normalFontSize || fontBold != normalFontBold || fontItalic != normalFontItalic || fontColor != normalFontColor {
		colorStr := bgrToRgb(fontColor)
		style.Font = &FontStyle{
			Bold:   &fontBold,
			Italic: &fontItalic,
			Size:   &fontSize,
			Color:  &colorStr,
		}
	}

	// Get Interior (fill) information
	interior := oleutil.MustGetProperty(rng, "Interior").ToIDispatch()
	defer interior.Release()

	interiorPattern := excelPatternToFillPattern(oleutil.MustGetProperty(interior, "Pattern").Value().(int32))

	if interiorPattern != FillPatternNone {
		interiorColor := oleutil.MustGetProperty(interior, "Color").Value().(float64)

		style.Fill = &FillStyle{
			Type:    "pattern",
			Pattern: interiorPattern,
			Color:   []string{bgrToRgb(interiorColor)},
		}
	}

	// Get Border information
	var borderStyles []Border

	// Get borders for each direction: Left(7), Top(8), Bottom(9), Right(10)
	borderPositions := []struct {
		index    int
		position BorderType
	}{
		{7, BorderTypeLeft},
		{8, BorderTypeTop},
		{9, BorderTypeBottom},
		{10, BorderTypeRight},
	}

	borders := oleutil.MustGetProperty(rng, "Borders").ToIDispatch()
	defer borders.Release()
	bordersLineStyle := oleutil.MustGetProperty(borders, "LineStyle")
	if bordersLineStyle.VT == ole.VT_NULL {
		// If Borders.LineStyle is null, the borders have different styles
		for _, pos := range borderPositions {
			border := oleutil.MustGetProperty(borders, "Item", pos.index).ToIDispatch()
			defer border.Release()

			borderLineStyle := excelBorderStyleToName(oleutil.MustGetProperty(border, "LineStyle").Value().(int32))

			if borderLineStyle != BorderStyleNone {
				borderColor := oleutil.MustGetProperty(border, "Color").Value().(float64)
				borderStyle := Border{
					Type:  pos.position,
					Style: borderLineStyle,
					Color: bgrToRgb(borderColor),
				}
				borderStyles = append(borderStyles, borderStyle)
			}
		}
	} else {
		// If Borders.LineStyle is not null, all borders have the same style
		lineStyle := excelBorderStyleToName(bordersLineStyle.Value().(int32))
		if lineStyle != BorderStyleNone {
			for _, pos := range borderPositions {
				border := oleutil.MustGetProperty(borders, "Item", pos.index).ToIDispatch()
				borderColor := oleutil.MustGetProperty(border, "Color").Value().(float64)
				borderStyle := Border{
					Type:  pos.position,
					Style: lineStyle,
					Color: bgrToRgb(borderColor),
				}
				borderStyles = append(borderStyles, borderStyle)
			}
		}
	}

	style.Border = borderStyles

	// Get NumberFormat information
	generalNumberFormat := oleutil.MustGetProperty(o.excel.application, "International", 26).Value().(string) // xlGeneralFormatName
	numberFormat := oleutil.MustGetProperty(rng, "NumberFormat").ToString()
	if numberFormat != generalNumberFormat && numberFormat != "@" {
		style.NumFmt = &numberFormat
	}

	// Extract decimal places from number format if it's a numeric format
	decimalPlaces := extractDecimalPlacesFromFormat(numberFormat)
	style.DecimalPlaces = &decimalPlaces

	return style, nil
}

// bgrToRgb converts BGR color format to RGB hex string
func bgrToRgb(bgrColor float64) string {
	bgrColorInt := int32(bgrColor)
	// Extract RGB components from BGR format
	r := (bgrColorInt >> 0) & 0xFF
	g := (bgrColorInt >> 8) & 0xFF
	b := (bgrColorInt >> 16) & 0xFF
	return fmt.Sprintf("#%02X%02X%02X", r, g, b)
}

// excelBorderStyleToName converts Excel border style constant to BorderStyleName
func excelBorderStyleToName(excelStyle int32) BorderStyle {
	switch excelStyle {
	case 1: // xlContinuous
		return BorderStyleContinuous
	case -4115: // xlDash
		return BorderStyleDash
	case -4118: // xlDot
		return BorderStyleDot
	case -4119: // xlDouble
		return BorderStyleDouble
	case 4: // xlDashDot
		return BorderStyleDashDot
	case 5: // xlDashDotDot
		return BorderStyleDashDotDot
	case 13: // xlSlantDashDot
		return BorderStyleSlantDashDot
	case -4142: // xlLineStyleNone
		return BorderStyleNone
	default:
		return BorderStyleNone
	}
}

// excelPatternToFillPattern converts Excel XlPattern constant to FillPatternName
func excelPatternToFillPattern(excelPattern int32) FillPattern {
	switch excelPattern {
	case -4142: // xlPatternNone
		return FillPatternNone
	case 1: // xlPatternSolid
		return FillPatternSolid
	case -4125: // xlPatternGray75
		return FillPatternDarkGray
	case -4124: // xlPatternGray50
		return FillPatternMediumGray
	case -4126: // xlPatternGray25
		return FillPatternLightGray
	case -4121: // xlPatternGray16
		return FillPatternGray125
	case -4127: // xlPatternGray8
		return FillPatternGray0625
	case 9: // xlPatternHorizontal
		return FillPatternLightHorizontal
	case 12: // xlPatternVertical
		return FillPatternLightVertical
	case 10: // xlPatternDown
		return FillPatternLightDown
	case 11: // xlPatternUp
		return FillPatternLightUp
	case 16: // xlPatternGrid
		return FillPatternLightGrid
	case 17: // xlPatternCrissCross
		return FillPatternLightTrellis
	case 5: // xlPatternLightHorizontal
		return FillPatternLightHorizontal
	case 6: // xlPatternLightVertical
		return FillPatternLightVertical
	case 7: // xlPatternLightDown
		return FillPatternLightDown
	case 8: // xlPatternLightUp
		return FillPatternLightUp
	case 15: // xlPatternLightGrid
		return FillPatternLightGrid
	case 18: // xlPatternLightTrellis
		return FillPatternLightTrellis
	case 13: // xlPatternSemiGray75
		return FillPatternDarkHorizontal
	case 2: // xlPatternDarkHorizontal
		return FillPatternDarkHorizontal
	case 3: // xlPatternDarkVertical
		return FillPatternDarkVertical
	case 4: // xlPatternDarkDown
		return FillPatternDarkDown
	case 14: // xlPatternDarkUp
		return FillPatternDarkUp
	case -4162: // xlPatternDarkGrid
		return FillPatternDarkGrid
	case -4166: // xlPatternDarkTrellis
		return FillPatternDarkTrellis
	default:
		return FillPatternNone
	}
}

var extractDecimalPlacesRegexp = regexp.MustCompile(`\.([0#]+)`)

// extractDecimalPlacesFromFormat extracts decimal places count from Excel number format string
func extractDecimalPlacesFromFormat(format string) int {
	// Handle common numeric formats
	// Examples: "0.00" -> 2, "#,##0.000" -> 3, "0" -> 0
	matches := extractDecimalPlacesRegexp.FindStringSubmatch(format)
	if len(matches) > 1 {
		return len(matches[1])
	}
	return 0
}

func (o *OleWorksheet) SetCellStyle(cell string, style *CellStyle) error {
	rng := oleutil.MustGetProperty(o.worksheet, "Range", cell).ToIDispatch()
	defer rng.Release()

	// Apply Font styles
	if style.Font != nil {
		font := oleutil.MustGetProperty(rng, "Font").ToIDispatch()
		defer font.Release()

		if style.Font.Bold != nil {
			oleutil.PutProperty(font, "Bold", *style.Font.Bold)
		}
		if style.Font.Italic != nil {
			oleutil.PutProperty(font, "Italic", *style.Font.Italic)
		}
		if style.Font.Size != nil && *style.Font.Size > 0 {
			oleutil.PutProperty(font, "Size", *style.Font.Size)
		}
		if style.Font.Color != nil && *style.Font.Color != "" {
			colorValue := rgbToBgr(*style.Font.Color)
			oleutil.PutProperty(font, "Color", colorValue)
		}
		if style.Font.Strike != nil && *style.Font.Strike {
			oleutil.PutProperty(font, "Strikethrough", true)
		}
	}

	// Apply Fill styles
	if style.Fill != nil {
		interior := oleutil.MustGetProperty(rng, "Interior").ToIDispatch()
		defer interior.Release()

		if style.Fill.Pattern != FillPatternNone {
			oleutil.PutProperty(interior, "Pattern", fillPatternToExcelPattern(style.Fill.Pattern))
		}
		if len(style.Fill.Color) > 0 && style.Fill.Color[0] != "" {
			colorValue := rgbToBgr(style.Fill.Color[0])
			oleutil.PutProperty(interior, "Color", colorValue)
		}
	}

	// Apply Border styles
	if len(style.Border) > 0 {
		borders := oleutil.MustGetProperty(rng, "Borders").ToIDispatch()
		defer borders.Release()

		for _, borderStyle := range style.Border {
			borderIndex := borderTypeToIndex(borderStyle.Type)
			if borderIndex > 0 {
				border := oleutil.MustGetProperty(borders, "Item", borderIndex).ToIDispatch()
				defer border.Release()

				oleutil.PutProperty(border, "LineStyle", borderStyleNameToExcel(borderStyle.Style))
				if borderStyle.Color != "" {
					colorValue := rgbToBgr(borderStyle.Color)
					oleutil.PutProperty(border, "Color", colorValue)
				}
			}
		}
	}

	// Apply Number Format
	if style.NumFmt != nil && *style.NumFmt != "" {
		oleutil.PutProperty(rng, "NumberFormat", *style.NumFmt)
	}

	return nil
}

// rgbToBgr converts RGB hex string to BGR color format
func rgbToBgr(rgbColor string) int32 {
	if len(rgbColor) != 7 || rgbColor[0] != '#' {
		return 0
	}

	r := hexToByte(rgbColor[1:3])
	g := hexToByte(rgbColor[3:5])
	b := hexToByte(rgbColor[5:7])

	return int32(r) | (int32(g) << 8) | (int32(b) << 16)
}

// hexToByte converts hex string to byte
func hexToByte(hex string) byte {
	var result byte
	for _, char := range hex {
		result *= 16
		if char >= '0' && char <= '9' {
			result += byte(char - '0')
		} else if char >= 'A' && char <= 'F' {
			result += byte(char - 'A' + 10)
		} else if char >= 'a' && char <= 'f' {
			result += byte(char - 'a' + 10)
		}
	}
	return result
}

// borderTypeToIndex converts border type string to Excel border index
func borderTypeToIndex(borderType BorderType) int {
	switch borderType {
	case BorderTypeLeft:
		return 7
	case BorderTypeTop:
		return 8
	case BorderTypeBottom:
		return 9
	case BorderTypeRight:
		return 10
	case BorderTypeDiagonalDown:
		return 5
	case BorderTypeDiagonalUp:
		return 6
	default:
		return 0
	}
}

// borderStyleNameToExcel converts BorderStyleName to Excel constant
func borderStyleNameToExcel(style BorderStyle) int32 {
	switch style {
	case BorderStyleContinuous:
		return 1 // xlContinuous
	case BorderStyleDash:
		return -4115 // xlDash
	case BorderStyleDot:
		return -4118 // xlDot
	case BorderStyleDouble:
		return -4119 // xlDouble
	case BorderStyleDashDot:
		return 4 // xlDashDot
	case BorderStyleDashDotDot:
		return 5 // xlDashDotDot
	case BorderStyleSlantDashDot:
		return 13 // xlSlantDashDot
	case BorderStyleNone:
		return -4142 // xlLineStyleNone
	default:
		return -4142 // xlLineStyleNone
	}
}

// fillPatternToExcelPattern converts FillPatternName to Excel pattern constant
func fillPatternToExcelPattern(pattern FillPattern) int32 {
	switch pattern {
	case FillPatternSolid:
		return 1 // xlPatternSolid
	case FillPatternMediumGray:
		return -4124 // xlPatternGray50
	case FillPatternDarkGray:
		return -4125 // xlPatternGray75
	case FillPatternLightGray:
		return -4126 // xlPatternGray25
	case FillPatternGray125:
		return -4121 // xlPatternGray16
	case FillPatternGray0625:
		return -4127 // xlPatternGray8
	case FillPatternLightHorizontal:
		return 5 // xlPatternLightHorizontal
	case FillPatternLightVertical:
		return 6 // xlPatternLightVertical
	case FillPatternLightDown:
		return 7 // xlPatternLightDown
	case FillPatternLightUp:
		return 8 // xlPatternLightUp
	case FillPatternLightGrid:
		return 15 // xlPatternLightGrid
	case FillPatternLightTrellis:
		return 18 // xlPatternLightTrellis
	case FillPatternDarkHorizontal:
		return 2 // xlPatternDarkHorizontal
	case FillPatternDarkVertical:
		return 3 // xlPatternDarkVertical
	case FillPatternDarkDown:
		return 4 // xlPatternDarkDown
	case FillPatternDarkUp:
		return 14 // xlPatternDarkUp
	case FillPatternDarkGrid:
		return -4162 // xlPatternDarkGrid
	case FillPatternDarkTrellis:
		return -4166 // xlPatternDarkTrellis
	case FillPatternNone:
		return -4142 // xlPatternNone
	default:
		return -4142 // xlPatternNone
	}
}

func normalizePath(path string) string {
	// Normalize the volume name to uppercase
	vol := filepath.VolumeName(path)
	if vol == "" {
		return path
	}
	rest := path[len(vol):]
	return filepath.Clean(strings.ToUpper(vol) + rest)
}
