export interface MetadataInfo {
  fullName: string;
  label: string;
  pluralLabel?: string;
  nameField?: {
    type: string;
    label: string;
    displayFormat?: string;
  };
  deploymentStatus?: 'Deployed' | 'InDevelopment';
  sharingModel?: 'ReadWrite' | 'Read' | 'Private' | 'ControlledByParent';
  enableActivities?: boolean;
  description?: string;
}

export interface ValueSetDefinition {
  sorted?: boolean;
  value: Array<{
    fullName: string;
    default?: boolean;
    label: string;
  }>;
}

export interface FieldMetadataInfo {
  fullName: string;
  label: string;
  type: string;
  required?: boolean;
  unique?: boolean;
  externalId?: boolean;
  length?: number;
  precision?: number;
  scale?: number;
  visibleLines?: number;
  referenceTo?: string;
  relationshipLabel?: string;
  relationshipName?: string;
  deleteConstraint?: 'Cascade' | 'Restrict' | 'SetNull';
  valueSet?: {
    valueSetDefinition: ValueSetDefinition;
  };
  defaultValue?: string | number | boolean;
  description?: string;
}