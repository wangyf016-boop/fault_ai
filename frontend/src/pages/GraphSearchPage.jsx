import React from 'react';
import Neo4jGraph from '../components/chat/Neo4jGraph';

const GraphSearchPage = () => {
  return (
    <Neo4jGraph
      keyword=""
      allowKeywordSearch={true}
      autoLoad={false}
      lightTheme={true}
      showPaths={true}
      defaultLimit={50}
      limitOptions={[20, 50, 100, 200, 300]}
    />
  );
};

export default GraphSearchPage;
