package org.analysis;

import java.math.BigDecimal;

public class DeltaAnalysisParameters extends AnalysisParameters{
    protected BigDecimal delta;

    public DeltaAnalysisParameters() {
        super();
        this.delta = BigDecimal.ZERO;
    }
    public DeltaAnalysisParameters(BigDecimal maxTime, BigDecimal error, BigDecimal delta) {
        super(maxTime, error);
        this.delta = delta;
    }

    public BigDecimal getDelta() {
        return delta;
    }
    public void setDelta(BigDecimal delta) {
        this.delta = delta;
    }
}
