import { useState } from "react";
import { searchLabTests } from "../api/labApi";

export const useLabSearch = () => {
  const [tests, setTests] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const search = async (payload) => {
    try {
      setLoading(true);
      setError(null);

      const res = await searchLabTests(payload);

      setTests(res.data.tests || []);
    } catch (err) {
      console.log("Search error:", err);
      setError("Something went wrong");
    } finally {
      setLoading(false);
    }
  };

  return {
    tests,
    loading,
    error,
    search,
  };
};