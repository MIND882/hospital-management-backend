import React, { useEffect, useState } from "react";
import { View, FlatList, Text } from "react-native";

import { useLabSearch } from "../hooks/useLabSearch";
import LabTestCard from "../components/LabTestCard";
import SearchBar from "@/src/components/common/SearchBar";
import LoadingSpinner from "@/src/components/common/LoadingSpinner";

const LabTestSearchScreen = () => {
  const { tests, loading, error, search } = useLabSearch();
  const [query, setQuery] = useState("");

  useEffect(() => {
    // initial load
    search({
      query: "",
      page: 1,
      limit: 10,
    });
  }, []);

  const handleSearch = (text) => {
    setQuery(text);

    search({
      query: text,
      page: 1,
      limit: 10,
    });
  };

  return (
    <View style={{ flex: 1, padding: 16 }}>
      
      {/* 🔍 Search */}
      <SearchBar value={query} onChangeText={handleSearch} />

      {/* ⏳ Loading */}
      {loading && <LoadingSpinner />}

      {/* ❌ Error */}
      {error && <Text>{error}</Text>}

      {/* 📋 List */}
      <FlatList
        data={tests}
        keyExtractor={(item) => item.test_id.toString()}
        renderItem={({ item }) => (
          <LabTestCard test={item} />
        )}
      />
    </View>
  );
};

export default LabTestSearchScreen;