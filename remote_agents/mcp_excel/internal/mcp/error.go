package mcp

import (
	"fmt"

	z "github.com/Oudwins/zog"
	"github.com/mark3labs/mcp-go/mcp"
)

func NewToolResultInvalidArgumentError(message string) *mcp.CallToolResult {
	return mcp.NewToolResultError(fmt.Sprintf("Invalid argument: %s", message))
}

func NewToolResultZogIssueMap(errs z.ZogIssueMap) *mcp.CallToolResult {
	issues := z.Issues.SanitizeMap(errs)

	var issueResults []mcp.Content
	for k, messages := range issues {
		for _, message := range messages {
			issueResults = append(issueResults, mcp.NewTextContent(fmt.Sprintf("Invalid argument: %s: %s", k, message)))
		}
	}

	return &mcp.CallToolResult{
		Content: issueResults,
		IsError: true,
	}
}
