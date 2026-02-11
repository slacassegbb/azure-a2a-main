interface ErrorResult {
    success: boolean;
    fullName?: string;
    errors?: Array<{ message: string; statusCode?: string; fields?: string | string[]; }> | 
            { message: string; statusCode?: string; fields?: string | string[]; };
  }
  
  export function formatMetadataError(result: ErrorResult | ErrorResult[], operation: string): string {
    let errorMessage = `Failed to ${operation}`;
    const saveResult = Array.isArray(result) ? result[0] : result;
    
    if (saveResult && saveResult.errors) {
      if (Array.isArray(saveResult.errors)) {
        errorMessage += ': ' + saveResult.errors.map((e: { message: string }) => e.message).join(', ');
      } else if (typeof saveResult.errors === 'object') {
        const error = saveResult.errors;
        errorMessage += `: ${error.message}`;
        if (error.fields) {
          errorMessage += ` (Field: ${error.fields})`;
        }
        if (error.statusCode) {
          errorMessage += ` [${error.statusCode}]`;
        }
      } else {
        errorMessage += ': ' + String(saveResult.errors);
      }
    }
  
    return errorMessage;
  }