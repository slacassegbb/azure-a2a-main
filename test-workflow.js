// Simulate the workflow generation logic
const steps = [
  { id: 's1', agentName: 'Step1', description: 'Gather requirements' },
  { id: 's2a', agentName: 'Legal', description: 'Legal review' },
  { id: 's2b', agentName: 'Tech', description: 'Technical assessment' },
  { id: 's3', agentName: 'Report', description: 'Generate report' }
];

// s1 -> s2a, s1 -> s2b (parallel), s2a -> s3, s2b -> s3 (merge)
const conns = [
  { fromStepId: 's1', toStepId: 's2a' },
  { fromStepId: 's1', toStepId: 's2b' },
  { fromStepId: 's2a', toStepId: 's3' },
  { fromStepId: 's2b', toStepId: 's3' }
];

// Build adjacency maps
const outgoing = new Map();
const incoming = new Map();

conns.forEach(conn => {
  if (!outgoing.has(conn.fromStepId)) outgoing.set(conn.fromStepId, []);
  outgoing.get(conn.fromStepId).push(conn.toStepId);
  
  if (!incoming.has(conn.toStepId)) incoming.set(conn.toStepId, []);
  incoming.get(conn.toStepId).push(conn.fromStepId);
});

const connectedStepIds = new Set();
conns.forEach(conn => {
  connectedStepIds.add(conn.fromStepId);
  connectedStepIds.add(conn.toStepId);
});

// Find root nodes
const hasIncoming = new Set(conns.map(c => c.toStepId));
const rootNodes = steps.filter(step => 
  connectedStepIds.has(step.id) && !hasIncoming.has(step.id)
);

console.log('Root nodes:', rootNodes.map(n => n.id));

// BFS with parallel detection
const entries = [];
const visited = new Set();
let currentStepNumber = 0;

const queue = [];

if (rootNodes.length > 1) {
  rootNodes.forEach((node, idx) => {
    queue.push({ stepId: node.id, parentNumber: 0, parallelSiblings: rootNodes.map(n => n.id), siblingIndex: idx });
  });
} else {
  rootNodes.forEach(node => {
    queue.push({ stepId: node.id, parentNumber: 0, parallelSiblings: [], siblingIndex: 0 });
  });
}

while (queue.length > 0) {
  const { stepId, parentNumber, parallelSiblings, siblingIndex } = queue.shift();
  
  if (visited.has(stepId)) continue;
  visited.add(stepId);
  
  const step = steps.find(s => s.id === stepId);
  if (!step) continue;
  
  let stepNumber;
  let subLetter;
  
  if (parallelSiblings.length > 1) {
    stepNumber = parentNumber + 1;
    subLetter = String.fromCharCode(97 + siblingIndex);
  } else {
    currentStepNumber++;
    stepNumber = currentStepNumber;
  }
  
  entries.push({ stepNumber, subLetter, step });
  console.log('Added:', stepNumber + (subLetter || ''), step.description);
  
  const children = outgoing.get(stepId) || [];
  if (children.length > 1) {
    children.forEach((childId, idx) => {
      queue.push({ stepId: childId, parentNumber: stepNumber, parallelSiblings: children, siblingIndex: idx });
    });
  } else if (children.length === 1) {
    queue.push({ stepId: children[0], parentNumber: stepNumber, parallelSiblings: [], siblingIndex: 0 });
  }
  
  if (parallelSiblings.length <= 1) {
    // Sequential
  } else if (siblingIndex === parallelSiblings.length - 1) {
    currentStepNumber = stepNumber;
  }
}

entries.sort((a, b) => {
  if (a.stepNumber !== b.stepNumber) return a.stepNumber - b.stepNumber;
  return (a.subLetter || '').localeCompare(b.subLetter || '');
});

console.log('\n=== GENERATED WORKFLOW ===');
entries.forEach(entry => {
  const label = entry.subLetter ? entry.stepNumber + entry.subLetter : String(entry.stepNumber);
  console.log(label + '. ' + entry.step.description);
});
