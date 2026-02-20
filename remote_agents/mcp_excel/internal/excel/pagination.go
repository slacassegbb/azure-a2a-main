package excel

import (
	"fmt"
	"github.com/xuri/excelize/v2"
)

// PagingStrategy はページング範囲の計算戦略を定義するインターフェース
type PagingStrategy interface {
	// CalculatePagingRanges は利用可能なページング範囲のリストを返す
	CalculatePagingRanges() []string
}

// ExcelizeFixedSizePagingStrategy は固定サイズでページング範囲を計算する戦略
type ExcelizeFixedSizePagingStrategy struct {
	pageSize  int
	worksheet *ExcelizeWorksheet
	dimension string
}

// NewExcelizeFixedSizePagingStrategy は新しいFixedSizePagingStrategyインスタンスを生成する
func NewExcelizeFixedSizePagingStrategy(pageSize int, worksheet *ExcelizeWorksheet) (*ExcelizeFixedSizePagingStrategy, error) {
	if pageSize <= 0 {
		pageSize = 5000 // デフォルト値
	}

	// シートの次元情報を取得
	dimension, err := worksheet.GetDimention()
	if err != nil {
		return nil, err
	}

	return &ExcelizeFixedSizePagingStrategy{
		pageSize:  pageSize,
		worksheet: worksheet,
		dimension: dimension,
	}, nil
}

// CalculatePagingRanges は固定サイズに基づいてページング範囲のリストを生成する
func (s *ExcelizeFixedSizePagingStrategy) CalculatePagingRanges() []string {
	startCol, startRow, endCol, endRow, err := ParseRange(s.dimension)
	if err != nil {
		return []string{}
	}

	totalCols := endCol - startCol + 1
	cellsPerPage := s.pageSize

	// 1ページあたりの行数を計算
	rowsPerPage := cellsPerPage / totalCols
	if rowsPerPage < 1 {
		rowsPerPage = 1
	}

	var ranges []string
	currentRow := startRow
	for currentRow <= endRow {
		pageEndRow := currentRow + rowsPerPage - 1
		if pageEndRow > endRow {
			pageEndRow = endRow
		}

		startRange, _ := excelize.CoordinatesToCellName(startCol, currentRow)
		endRange, _ := excelize.CoordinatesToCellName(endCol, pageEndRow)
		ranges = append(ranges, fmt.Sprintf("%s:%s", startRange, endRange))

		currentRow = pageEndRow + 1
	}

	return ranges
}


func NewOlePagingStrategy(pageSize int, worksheet *OleWorksheet) (PagingStrategy, error) {
	if worksheet == nil {
		return nil, fmt.Errorf("worksheet is nil")
	}

	printAreaPagingStrategy, err := NewPrintAreaPagingStrategy(worksheet)
	if err != nil {
		return nil, err
	}
	printArea, err := printAreaPagingStrategy.getPrintArea()
	if err != nil {
		return nil, err
	}
	if printArea == "" {
		return NewGoxcelFixedSizePagingStrategy(pageSize, worksheet)
	} else {
		return printAreaPagingStrategy, nil
	}
}

// OleFixedSizePagingStrategy は Goxcel を使用した固定サイズでページング範囲を計算する戦略
type OleFixedSizePagingStrategy struct {
	pageSize  int
	worksheet *OleWorksheet
	dimension string
}

// NewGoxcelFixedSizePagingStrategy は新しい GoxcelFixedSizePagingStrategy インスタンスを生成する
func NewGoxcelFixedSizePagingStrategy(pageSize int, worksheet *OleWorksheet) (*OleFixedSizePagingStrategy, error) {
	if pageSize <= 0 {
		pageSize = 5000 // デフォルト値
	}

	if worksheet == nil {
		return nil, fmt.Errorf("worksheet is nil")
	}

	// UsedRange を使用して使用範囲を取得
	dimention, err := worksheet.GetDimention()
	if err != nil {
		return nil, fmt.Errorf("failed to get dimention: %w", err)
	}

	return &OleFixedSizePagingStrategy{
		pageSize:  pageSize,
		worksheet: worksheet,
		dimension: dimention,
	}, nil
}

// CalculatePagingRanges は固定サイズに基づいてページング範囲のリストを生成する
func (s *OleFixedSizePagingStrategy) CalculatePagingRanges() []string {
	startCol, startRow, endCol, endRow, err := ParseRange(s.dimension)
	if err != nil {
		return []string{}
	}

	totalCols := endCol - startCol + 1
	cellsPerPage := s.pageSize

	// 1ページあたりの行数を計算
	rowsPerPage := cellsPerPage / totalCols
	if rowsPerPage < 1 {
		rowsPerPage = 1
	}

	var ranges []string
	currentRow := startRow
	for currentRow <= endRow {
		pageEndRow := currentRow + rowsPerPage - 1
		if pageEndRow > endRow {
			pageEndRow = endRow
		}

		startRange, _ := excelize.CoordinatesToCellName(startCol, currentRow)
		endRange, _ := excelize.CoordinatesToCellName(endCol, pageEndRow)
		ranges = append(ranges, fmt.Sprintf("%s:%s", startRange, endRange))

		currentRow = pageEndRow + 1
	}

	return ranges
}


// PrintAreaPagingStrategy は印刷範囲とページ区切りに基づいてページング範囲を計算する戦略
type PrintAreaPagingStrategy struct {
	worksheet *OleWorksheet
}

// NewPrintAreaPagingStrategy は新しいPrintAreaPagingStrategyインスタンスを生成する
func NewPrintAreaPagingStrategy(worksheet *OleWorksheet) (*PrintAreaPagingStrategy, error) {
	if worksheet == nil {
		return nil, fmt.Errorf("worksheet is nil")
	}
	return &PrintAreaPagingStrategy{
		worksheet: worksheet,
	}, nil
}

// getPrintArea は印刷範囲を取得する
func (s *PrintAreaPagingStrategy) getPrintArea() (string, error) {
	return s.worksheet.PrintArea()
}

// getHPageBreaksPositions はページ区切りの位置情報を取得する
func (s *PrintAreaPagingStrategy) getHPageBreaksPositions() ([]int, error) {
	pageBreaks, err := s.worksheet.HPageBreaks()
	if err != nil {
		return nil, fmt.Errorf("failed to get HPageBreaks: %w", err)
	}
	return pageBreaks, nil
}

// calculateRangesFromBreaks は印刷範囲とページ区切りから範囲のリストを生成する
func (s *PrintAreaPagingStrategy) calculateRangesFromBreaks(printArea string, breaks []int) []string {
	if printArea == "" {
		return []string{}
	}

	startCol, startRow, endCol, endRow, err := ParseRange(printArea)
	if err != nil {
		return []string{}
	}

	ranges := make([]string, 0)
	currentRow := startRow

	// ページ区切りがない場合は印刷範囲全体を1つの範囲として扱う
	if len(breaks) == 0 {
		startRange, _ := excelize.CoordinatesToCellName(startCol, startRow)
		endRange, _ := excelize.CoordinatesToCellName(endCol, endRow)
		ranges = append(ranges, fmt.Sprintf("%s:%s", startRange, endRange))
		return ranges
	}

	// ページ区切りで範囲を分割
	for _, breakRow := range breaks {
		if breakRow <= startRow || breakRow > endRow {
			continue
		}

		startRange, _ := excelize.CoordinatesToCellName(startCol, currentRow)
		endRange, _ := excelize.CoordinatesToCellName(endCol, breakRow-1)
		ranges = append(ranges, fmt.Sprintf("%s:%s", startRange, endRange))

		currentRow = breakRow
	}

	// 最後の範囲を追加
	if currentRow <= endRow {
		startRange, _ := excelize.CoordinatesToCellName(startCol, currentRow)
		endRange, _ := excelize.CoordinatesToCellName(endCol, endRow)
		ranges = append(ranges, fmt.Sprintf("%s:%s", startRange, endRange))
	}

	return ranges
}

// CalculatePagingRanges は印刷範囲とページ区切りに基づいてページング範囲のリストを生成する
func (s *PrintAreaPagingStrategy) CalculatePagingRanges() []string {
	printArea, err := s.getPrintArea()
	if err != nil {
		return []string{}
	}

	breaks, err := s.getHPageBreaksPositions()
	if err != nil {
		return []string{}
	}

	return s.calculateRangesFromBreaks(printArea, breaks)
}


// PagingRangeService はページング処理を提供するサービス
type PagingRangeService struct {
	strategy PagingStrategy
}

// NewPagingRangeService は新しいPagingRangeServiceインスタンスを生成する
func NewPagingRangeService(strategy PagingStrategy) *PagingRangeService {
	return &PagingRangeService{strategy: strategy}
}

// GetPagingRanges は利用可能なページング範囲のリストを返す
func (s *PagingRangeService) GetPagingRanges() []string {
	return s.strategy.CalculatePagingRanges()
}


// FilterRemainingPagingRanges は未読の範囲のリストを返す
func (s *PagingRangeService) FilterRemainingPagingRanges(allRanges []string, knownRanges []string) []string {
	if len(knownRanges) == 0 {
		return allRanges
	}

	// knownRanges をマップに変換
	knownMap := make(map[string]bool)
	for _, r := range knownRanges {
		knownMap[r] = true
	}

	// 未読の範囲を抽出
	remaining := make([]string, 0)
	for _, r := range allRanges {
		if !knownMap[r] {
			remaining = append(remaining, r)
		}
	}

	return remaining
}

// FindNextRange returns the next range in the sequence after the current range
func (s *PagingRangeService) FindNextRange(allRanges []string, currentRange string) string {
	for i, r := range allRanges {
		if r == currentRange && i+1 < len(allRanges) {
			return allRanges[i+1]
		}
	}
	return ""
}
