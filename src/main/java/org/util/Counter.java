package org.util;

public class Counter {
    private int counter;

    public Counter(int counterStart){
        this.counter = counterStart;
    }

    public int getCounter() {
        return counter;
    }

    public int addOne(){
        this.counter = this.counter + 1;
        return this.counter;
    }
}
