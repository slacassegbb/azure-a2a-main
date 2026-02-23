package tools

import (
	z "github.com/Oudwins/zog"
	"github.com/Oudwins/zog/zenv"
)

type EnvConfig struct {
	EXCEL_MCP_PAGING_CELLS_LIMIT int
}

var configSchema = z.Struct(z.Shape{
	"EXCEL_MCP_PAGING_CELLS_LIMIT": z.Int().GT(0).Default(4000),
})

func LoadConfig() (EnvConfig, z.ZogIssueMap) {
	config := EnvConfig{}
	issues := configSchema.Parse(zenv.NewDataProvider(), &config)
	return config, issues
}
