package org.faultTree.util;

public interface PrintTarget {
	void printf(String format, Object... args);


	@Deprecated void println(String str);
	@Deprecated void print(String str);

	void print(char c);
	void flush();
}
