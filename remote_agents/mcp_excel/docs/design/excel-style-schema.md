# MCP Excel Style Structure Definition

This document presents JsonSchema definitions for exchanging Excel styles through MCP (Model Context Protocol), based on the Excelize library's style API.

## Target Style Elements

- Border
- Font
- Fill
- NumFmt (Number Format)
- DecimalPlaces

## JsonSchema Definition

### ExcelStyle Structure

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "title": "ExcelStyle",
  "description": "Excel cell style configuration",
  "properties": {
    "border": {
      "type": "array",
      "description": "Border configuration for cell edges",
      "items": {
        "$ref": "#/definitions/Border"
      }
    },
    "font": {
      "$ref": "#/definitions/Font",
      "description": "Font configuration"
    },
    "fill": {
      "$ref": "#/definitions/Fill",
      "description": "Fill pattern and color configuration"
    },
    "numFmt": {
      "type": "string",
      "description": "Custom number format string",
      "example": "#,##0.00"
    },
    "decimalPlaces": {
      "type": "integer",
      "description": "Number of decimal places (0-30)",
      "minimum": 0,
      "maximum": 30
    }
  },
  "definitions": {
    "Border": {
      "type": "object",
      "description": "Border style configuration",
      "properties": {
        "type": {
          "type": "string",
          "description": "Border position",
          "enum": ["left", "right", "top", "bottom", "diagonalDown", "diagonalUp"]
        },
        "color": {
          "type": "string",
          "description": "Border color in hex format",
          "pattern": "^#[0-9A-Fa-f]{6}$",
          "example": "#000000"
        },
        "style": {
          "type": "string",
          "description": "Border style",
          "enum": ["none", "continuous", "dash", "dashDot", "dashDotDot", "dot", "double", "hair", "medium", "mediumDash", "mediumDashDot", "mediumDashDotDot", "slantDashDot", "thick"]
        }
      },
      "required": ["type"],
      "additionalProperties": false
    },
    "Font": {
      "type": "object",
      "description": "Font style configuration",
      "properties": {
        "bold": {
          "type": "boolean",
          "description": "Bold text"
        },
        "italic": {
          "type": "boolean",
          "description": "Italic text"
        },
        "underline": {
          "type": "string",
          "description": "Underline style",
          "enum": ["none", "single", "double", "singleAccounting", "doubleAccounting"]
        },
        "size": {
          "type": "number",
          "description": "Font size in points",
          "minimum": 1,
          "maximum": 409
        },
        "strike": {
          "type": "boolean",
          "description": "Strikethrough text"
        },
        "color": {
          "type": "string",
          "description": "Font color in hex format",
          "pattern": "^#[0-9A-Fa-f]{6}$",
          "example": "#000000"
        },
        "vertAlign": {
          "type": "string",
          "description": "Vertical alignment",
          "enum": ["baseline", "superscript", "subscript"]
        }
      },
      "additionalProperties": false
    },
    "Fill": {
      "type": "object",
      "description": "Fill pattern and color configuration",
      "properties": {
        "type": {
          "type": "string",
          "description": "Fill type",
          "enum": ["gradient", "pattern"]
        },
        "pattern": {
          "type": "string",
          "description": "Pattern style",
          "enum": ["none", "solid", "mediumGray", "darkGray", "lightGray", "darkHorizontal", "darkVertical", "darkDown", "darkUp", "darkGrid", "darkTrellis", "lightHorizontal", "lightVertical", "lightDown", "lightUp", "lightGrid", "lightTrellis", "gray125", "gray0625"]
        },
        "color": {
          "type": "array",
          "description": "Fill colors in hex format",
          "items": {
            "type": "string",
            "pattern": "^#[0-9A-Fa-f]{6}$",
            "example": "#FFFFFF"
          }
        },
        "shading": {
          "type": "string",
          "description": "Gradient shading direction",
          "enum": ["horizontal", "vertical", "diagonalDown", "diagonalUp", "fromCenter", "fromCorner"]
        }
      },
      "additionalProperties": false
    }
  }
}
```

## Usage Examples

### Basic Style Configuration

```json
{
  "font": {
    "bold": true,
    "size": 12,
    "color": "#000000"
  },
  "fill": {
    "type": "pattern",
    "pattern": "solid",
    "color": ["#FFFF00"]
  }
}
```

### Style with Borders

```json
{
  "border": [
    {
      "type": "top",
      "style": "continuous",
      "color": "#000000"
    },
    {
      "type": "bottom",
      "style": "continuous",
      "color": "#000000"
    }
  ],
  "font": {
    "size": 10
  }
}
```

### Style with Number Format

```json
{
  "numFmt": "#,##0.00",
  "decimalPlaces": 2,
  "font": {
    "size": 11
  }
}
```

## Implementation Notes

1. **Required Fields**: Only Border's `type` field is required; all others are optional
2. **Color Format**: Hexadecimal color codes (#RRGGBB format)
3. **Numeric Limits**: 
   - `decimalPlaces`: Range 0-30
   - `border.style`: String identifiers (none, continuous, dash, etc.)
   - `fill.pattern`: String identifiers (none, solid, mediumGray, etc.)
   - `fill.shading`: String identifiers (horizontal, vertical, etc.)
   - `font.size`: Range 1-409
4. **Testing**: After implementation, test with actual Excel files

## Correspondence with Excelize

This definition is based on the style structure of `github.com/xuri/excelize/v2 v2.9.0` and maintains compatibility with Excelize's API specifications.