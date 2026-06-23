package org.analysis;

import java.math.BigDecimal;

public abstract class AnalysisParameters {

    protected BigDecimal maxTime;
    protected BigDecimal error;

    public AnalysisParameters() {
        this.maxTime = BigDecimal.ZERO;
        this.error = BigDecimal.ZERO;
    }

    public AnalysisParameters(BigDecimal maxTime, BigDecimal error) {
      this.maxTime = maxTime;
      this.error = error;
    }

    public BigDecimal getMaxTime()  {
        return maxTime;
    }

    public void setMaxTime(BigDecimal maxTime) {
        this.maxTime = maxTime;
    }

    public BigDecimal getError() {
        return error;
    }

    public void setError(BigDecimal error) {
        this.error = error;
    }
}
